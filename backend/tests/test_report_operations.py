import asyncio
from contextlib import asynccontextmanager
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta
import json
import multiprocessing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from backend.advisor.operations import OperationBusy, OperationStore
from backend.advisor.report_workflow import build_report_graph
from backend.services.report.provenance import execution_context
from backend.services.report import workflow as report_service


def hold_workflow(path, pipe):
    store = OperationStore(path)
    with store.workflow_lock("user:report"):
        pipe.send("locked")
        pipe.recv()


def crash_in_operation(path, pipe, after_commit):
    import os
    store = OperationStore(path)
    def operation():
        if not after_commit:
            pipe.send("calling")
            os._exit(23)
        return {"saved": True}
    store.call_sync("user:report", "test", {"input": 1}, {}, operation)
    pipe.send("committed")
    os._exit(23)


class StoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "operations.sqlite3"
        self.store = OperationStore(self.path)

    def rows(self):
        with self.store._connection() as connection:
            return [dict(row) for row in connection.execute("SELECT * FROM report_operations")]

    async def test_success_reused_after_store_reopened(self):
        operation = AsyncMock(return_value={"status": "ok", "data": {"answer": 1}})
        first = await self.store.call("a:r", "analysis", {"resume": "text"}, {"model": "one"}, operation)
        second = await OperationStore(self.path).call("a:r", "analysis", {"resume": "text"}, {"model": "one"}, operation)
        self.assertEqual(operation.await_count, 1)
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(second.attempts, 1)

    async def test_scope_payload_model_and_code_changes_do_not_reuse(self):
        operation = AsyncMock(return_value={"answer": "ok"})
        cases = [("a:r", "analysis", {"text": 1}, {"model": "one", "code": 1}),
                 ("b:r", "analysis", {"text": 1}, {"model": "one", "code": 1}),
                 ("a:other", "analysis", {"text": 1}, {"model": "one", "code": 1}),
                 ("a:r", "different-stage", {"text": 1}, {"model": "one", "code": 1}),
                 ("a:r", "analysis", {"text": 2}, {"model": "one", "code": 1}),
                 ("a:r", "analysis", {"text": 1}, {"model": "two", "code": 1}),
                 ("a:r", "analysis", {"text": 1}, {"model": "one", "code": 2})]
        ids = set()
        for args in cases:
            outcome = await self.store.call(*args, operation)
            ids.add(outcome.operation_id)
        self.assertEqual(len(ids), len(cases))
        self.assertEqual(operation.await_count, len(cases))

    async def test_execution_metrics_do_not_invalidate_downstream_inputs(self):
        operation = AsyncMock(return_value={"answer": 1})
        result = {"agent": "resume_analysis", "status": "ok", "data": {"summary": "fact"}, "execution": {"model_calls": 1}}
        await self.store.call("a:r", "decision", {"analysis": result}, {}, operation)
        result["execution"].update(operation_reused=True, invocation_model_calls=0)
        replayed = await self.store.call("a:r", "decision", {"analysis": result}, {}, operation)
        self.assertTrue(replayed.reused)
        self.assertEqual(operation.await_count, 1)
        result["data"]["summary"] = "changed fact"
        self.assertFalse((await self.store.call("a:r", "decision", {"analysis": result}, {}, operation)).reused)

    async def test_failure_retries_and_does_not_record_exception_text(self):
        operation = AsyncMock(side_effect=[RuntimeError("private-api-key"), {"answer": 1}])
        with self.assertRaises(RuntimeError):
            await self.store.call("a:r", "analysis", {"private-input": "secret"}, {}, operation)
        row = self.rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error_type"], "RuntimeError")
        self.assertNotIn("private-api-key", json.dumps(row))
        self.assertNotIn("private-input", json.dumps(row))
        result = await self.store.call("a:r", "analysis", {"private-input": "secret"}, {}, operation)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(self.rows()[0]["status"], "succeeded")

    async def test_cancelled_operation_unlocks_and_can_retry(self):
        entered = asyncio.Event()
        async def wait():
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(self.store.call("a:r", "analysis", {}, {}, wait))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.rows()[0]["status"], "failed")
        result = await self.store.call("a:r", "analysis", {}, {}, AsyncMock(return_value={"answer": 1}))
        self.assertEqual(result.attempts, 2)

    async def test_concurrent_identical_operation_is_not_called_twice(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait():
            entered.set()
            await release.wait()
            return {"answer": 1}
        task = asyncio.create_task(self.store.call("a:r", "analysis", {}, {}, wait))
        await entered.wait()
        other = AsyncMock(return_value={"answer": 2})
        try:
            with self.assertRaises(OperationBusy):
                await OperationStore(self.path).call("a:r", "analysis", {}, {}, other)
            other.assert_not_awaited()
        finally:
            release.set()
            await task

    async def test_corrupt_success_does_not_trigger_new_provider_call(self):
        operation = AsyncMock(return_value={"answer": 1})
        await self.store.call("a:r", "analysis", {}, {}, operation)
        with self.store._connection() as connection:
            connection.execute("UPDATE report_operations SET result_json='{}'")
        with self.assertRaisesRegex(ValueError, "损坏"):
            await self.store.call("a:r", "analysis", {}, {}, operation)
        self.assertEqual(operation.await_count, 1)

    async def test_mutating_returned_result_does_not_mutate_saved_success(self):
        first = await self.store.call("a:r", "analysis", {}, {}, AsyncMock(return_value={"answer": [1]}))
        first.result["answer"].append(2)
        second = await self.store.call("a:r", "analysis", {}, {}, AsyncMock(side_effect=AssertionError))
        self.assertEqual(second.result, {"answer": [1]})

    async def test_insufficient_evidence_is_not_negative_cached(self):
        operation = AsyncMock(return_value={"status": "insufficient_evidence", "data": {}})
        for _ in range(2):
            outcome = await self.store.call("a:r", "job_analysis", {}, {}, operation,
                                             cache_if=lambda item: item["status"] == "ok")
            self.assertFalse(outcome.reused)
        self.assertEqual(operation.await_count, 2)
        self.assertIsNone(self.rows()[0]["result_json"])

    async def test_success_record_with_lost_owner_cannot_be_overwritten(self):
        async def steal():
            with self.store._connection() as connection:
                connection.execute("UPDATE report_operations SET owner='replacement'")
            return {"answer": 1}
        with self.assertRaisesRegex(RuntimeError, "写入权限"):
            await self.store.call("a:r", "analysis", {}, {}, steal)
        self.assertEqual(self.rows()[0]["owner"], "replacement")
        self.assertIsNone(self.rows()[0]["result_json"])

    def worker(self, target, *args):
        parent, child = multiprocessing.Pipe()
        process = multiprocessing.get_context("spawn").Process(target=target, args=(str(self.path), child, *args))
        process.start()
        child.close()
        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)
            parent.close()
            process.close()
        self.addCleanup(cleanup)
        self.assertTrue(parent.poll(15), "worker did not reach test operation")
        return process, parent

    def test_workflow_lock_excludes_other_process(self):
        process, pipe = self.worker(hold_workflow)
        self.assertEqual(pipe.recv(), "locked")
        with self.assertRaises(OperationBusy):
            with self.store.workflow_lock("user:report"):
                self.fail("A second process acquired the same workflow")
        with self.store.workflow_lock("different-report"):
            pass
        pipe.send("release")
        process.join(timeout=10)
        self.assertEqual(process.exitcode, 0)
        with self.store.workflow_lock("user:report"):
            pass

    def test_process_crash_before_commit_releases_lock_and_retries(self):
        process, pipe = self.worker(crash_in_operation, False)
        self.assertEqual(pipe.recv(), "calling")
        process.join(timeout=10)
        self.assertEqual(process.exitcode, 23)
        self.assertEqual(self.rows()[0]["status"], "running")
        outcome = self.store.call_sync("user:report", "test", {"input": 1}, {}, lambda: {"retried": True})
        self.assertFalse(outcome.reused)
        self.assertEqual(outcome.attempts, 2)

    def test_process_crash_after_commit_keeps_reusable_success(self):
        process, pipe = self.worker(crash_in_operation, True)
        self.assertEqual(pipe.recv(), "committed")
        process.join(timeout=10)
        outcome = self.store.call_sync("user:report", "test", {"input": 1}, {}, lambda: self.fail("Repeated provider call"))
        self.assertTrue(outcome.reused)
        self.assertEqual(outcome.result, {"saved": True})

    def test_execution_context_excludes_secrets_and_tracks_model_and_provider(self):
        context = execution_context({"base_url": "http://provider/v1/", "model": "one", "api_key": "secret"})
        self.assertNotIn("secret", json.dumps(context))
        self.assertEqual(context["base_url"], "http://provider/v1")
        self.assertNotEqual(context, execution_context({"base_url": "http://provider/v1", "model": "two"}))


class GraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = OperationStore(Path(self.tmp.name) / "operations.sqlite3")
        self.calls = Counter()
        self.fail = set()
        self.inputs = {"input": {"raw_resume": "简历原文", "targets": ["Python开发"], "job_filters": {}}}

    def factory(self, name):
        calls, failed = self.calls, self.fail
        class Agent:
            async def arun(self, payload, config=None):
                calls[name] += 1
                if name in failed:
                    return {"agent": name, "status": "model_error", "data": {}}
                data = {"summary": "依据当前材料分析", "findings": [], "related_roles": [], "limitations": []}
                if name == "career_decision":
                    data.update(assessments=[], evidence_requests=[])
                return {"agent": name, "status": "ok", "data": data, "sources": [],
                        "execution": {"model_calls": 1}}
        return Agent()

    def graph(self, saver=None, callback=None):
        return build_report_graph(lambda: None, checkpointer=saver or InMemorySaver(), agent_factory=self.factory,
            agent_status_callback=callback, operation_store=self.store, operation_context={"model": "fixture", "code": "v1"})

    async def test_success_survives_missing_graph_checkpoint(self):
        # Rebuild with an empty checkpointer to simulate successful operation commits
        # surviving while graph progress is lost; no provider should run again.
        config = {"configurable": {"thread_id": "user:report"}}
        await self.graph().ainvoke(deepcopy(self.inputs), config)
        counts = self.calls.copy()
        result = await self.graph().ainvoke(deepcopy(self.inputs), config)
        self.assertEqual(self.calls, counts)
        analysis = result["job_targets"]["T1"]
        self.assertTrue(analysis["execution"]["operation_reused"])
        self.assertEqual(analysis["execution"]["invocation_model_calls"], 0)

    async def test_failure_between_operation_commit_and_node_return_recovers(self):
        crashed = False
        def callback(name, status, detail):
            nonlocal crashed
            if name == "job_analysis" and status == "done" and not crashed:
                crashed = True
                raise RuntimeError("simulated interruption before node checkpoint")
        saver = InMemorySaver()
        graph = self.graph(saver, callback)
        config = {"configurable": {"thread_id": "user:report"}}
        with self.assertRaisesRegex(RuntimeError, "simulated interruption"):
            await graph.ainvoke(deepcopy(self.inputs), config)
        result = await self.graph(saver).ainvoke(None, config)
        self.assertEqual(self.calls["job_analysis"], 1)
        self.assertTrue(result["job_targets"]["T1"]["execution"]["operation_reused"])

    async def test_failed_agent_result_is_not_cached(self):
        self.fail.add("resume_analysis")
        config = {"configurable": {"thread_id": "user:report"}}
        with self.assertRaises(Exception):
            await self.graph().ainvoke(deepcopy(self.inputs), config)
        self.fail.clear()
        result = await self.graph().ainvoke(deepcopy(self.inputs), config)
        self.assertEqual(self.calls["resume_analysis"], 2)
        self.assertEqual(result["results"]["resume_analysis"]["execution"]["operation_attempts"], 2)

    async def test_date_sensitive_stages_are_not_reused_on_next_day(self):
        config = {"configurable": {"thread_id": "user:report"}}
        today = datetime.now(ZoneInfo("Asia/Shanghai"))
        with patch("backend.advisor.report_workflow.datetime", wraps=datetime) as clock:
            clock.now.return_value = today
            await self.graph().ainvoke(deepcopy(self.inputs), config)
            clock.now.return_value = today + timedelta(days=1)
            await self.graph().ainvoke(deepcopy(self.inputs), config)
        self.assertEqual(self.calls["job_analysis"], 1)
        self.assertEqual(self.calls["resume_analysis"], 2)
        self.assertEqual(self.calls["career_decision"], 2)

    async def test_persistent_checkpoint_reopens_and_resumes_user_review(self):
        path = str(Path(self.tmp.name) / "checkpoints.sqlite3")
        config = {"configurable": {"thread_id": "user:report"}}
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            await self.graph(saver).ainvoke(deepcopy(self.inputs), config, durability="sync")
        counts = self.calls.copy()
        async with AsyncSqliteSaver.from_conn_string(path) as saver:
            graph = self.graph(saver)
            snapshot = await graph.aget_state(config)
            self.assertEqual(snapshot.next, ("review",))
            result = await graph.ainvoke(Command(resume={"target_id": "T1", "constraints": {
                "weekly_hours": 10, "deadline": (datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=30)).date().isoformat()}}),
                config, durability="sync")
            self.assertFalse((await graph.aget_state(config)).next)
        self.assertEqual(self.calls["resume_analysis"], counts["resume_analysis"])
        self.assertEqual(self.calls["job_analysis"], counts["job_analysis"])
        self.assertEqual(self.calls["action_planning"], 1)
        self.assertIn("operation_id", result["results"]["action_planning"]["execution"])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.patch = patch.object(report_service, "APP_DATA_DIR", self.directory)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.arguments = {"username": "alice", "report_id": "report-123456abcdef",
            "profile_payload": {"agent_workflow": {}}, "runtime_llm": {"model": "fixture", "base_url": "http://test"}}

    def test_report_synthesis_reuses_success_and_preserves_generation_time(self):
        state = {"profile_snapshot": {}, "results": {}}
        bundle = {"meta": {"report_id": self.arguments["report_id"], "generated_at": "first timestamp"}}
        with patch.object(report_service, "_execute", new=AsyncMock(return_value=state)) as execute:
            with patch("backend.services.report.workflow_report.build_report_bundle", return_value=bundle) as build:
                first = report_service.generate_career_report_bundle(**self.arguments)
                second = report_service.generate_career_report_bundle(**self.arguments)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(first, second)
        self.assertIsInstance(execute.call_args.kwargs["operation_store"], OperationStore)

    def test_generation_entry_observes_workflow_lock(self):
        store = OperationStore(self.directory / "report_operations.sqlite3")
        with patch.object(report_service, "_execute", new=AsyncMock()) as execute:
            with store.workflow_lock(report_service._thread_id(self.arguments["username"], self.arguments["report_id"])):
                with self.assertRaises(OperationBusy):
                    report_service.generate_career_report_bundle(**self.arguments)
            execute.assert_not_awaited()

    def test_stale_checkpoint_rejected_before_invocation(self):
        fake = type("Graph", (), {})()
        fake.aget_state = AsyncMock(return_value=object())
        fake.ainvoke = AsyncMock()
        @asynccontextmanager
        async def graph(*args, **kwargs):
            yield fake
        with patch.object(report_service, "_graph", graph), patch.object(report_service, "_snapshot", return_value={"checkpoint_id": "new"}):
            with self.assertRaisesRegex(ValueError, "已有更新"):
                asyncio.run(report_service._execute("alice", "report-123456abcdef", {},
                    {"continuation": {"checkpoint_id": "old", "response": {}}}, None))
        fake.ainvoke.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
