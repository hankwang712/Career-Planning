import base64
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_chat import ChatChecks, FakeClient


class ImageChecks(unittest.TestCase):
    def setUp(self):
        self.case = ChatChecks(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.service = self.case.service
        self.store = self.service.store
        self.case.runtime = ("https://offline.invalid/v1", "offline-key", "deepseek-flash")
        self.sid = self.case.create()

    @staticmethod
    def image(color="red"):
        output = BytesIO()
        Image.new("RGB", (16, 12), color).save(output, format="PNG")
        return {"name": "截图.png", "data_url": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()}

    def send(self, *, images=None, content="请查看图片", request_id=None):
        return self.case.api("POST", f"/api/chat/sessions/{self.sid}/messages", {
            "content": content, "images": [self.image()] if images is None else images,
            "request_id": request_id or str(uuid4())})

    def saved_image(self):
        user = next(row for row in self.store.messages("alice", self.sid)["items"] if row["role"] == "user")
        return user["images"][0]

    def test_image_only_message_reaches_the_model_and_has_private_history(self):
        response = self.send(content="")
        self.assertEqual(response.status_code, 200)
        self.assertIn('"type": "done"', response.text)
        call = next(call for call in reversed(self.case.calls) if call.get("stream"))
        parts = call["messages"][-1]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "请分析上传的图片。"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        image = self.saved_image()
        self.assertEqual((image["width"], image["height"]), (16, 12))
        download = self.case.client.get(image["url"])
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"\x89PNG"))
        self.assertEqual(download.headers["cache-control"], "no-store")
        self.assertNotIn("base64", json.dumps(self.store.context_trace("alice", self.sid)))
        self.assertTrue(self.case.client.get("/api/chat/sessions").json()["image_input"])

    def test_image_access_requires_login_and_owner(self):
        self.send()
        image = self.saved_image()
        self.case.login("bob")
        self.assertEqual(self.case.client.get(image["url"]).status_code, 404)
        self.case.login(None)
        self.assertEqual(self.case.client.get(image["url"]).status_code, 401)

    def test_invalid_images_do_not_create_turns(self):
        for image in ({"name": "bad.png", "data_url": "data:image/png;base64,bm90IGFuIGltYWdl"},
                      {"name": "bad.svg", "data_url": "data:image/svg+xml;base64,PHN2Zz4="},
                      {"name": "remote.png", "data_url": "https://untrusted.invalid/private.png"}):
            with self.subTest(image=image["name"]):
                self.assertEqual(self.send(images=[image]).status_code, 400)
        self.assertEqual(self.send(images=[self.image()] * 4).status_code, 400)
        self.assertFalse(self.store.messages("alice", self.sid)["items"])

    def test_actual_image_content_determines_the_format(self):
        image = self.image()
        image["data_url"] = image["data_url"].replace("data:image/png;", "data:image/jpeg;")
        self.assertEqual(self.send(images=[image]).status_code, 200)
        self.assertEqual(self.saved_image()["mime"], "image/png")

    def test_non_visual_deepseek_model_is_rejected_before_saving(self):
        self.case.runtime = (*self.case.runtime[:2], "deepseek-v4-pro")
        self.assertFalse(self.case.client.get("/api/chat/sessions").json()["image_input"])
        self.assertEqual(self.send().status_code, 400)
        self.assertFalse(self.store.messages("alice", self.sid)["items"])
        self.assertFalse(self.case.calls)

    def test_oversized_image_is_rejected_without_creating_a_turn(self):
        image = self.image()
        raw = base64.b64decode(image["data_url"].split(",", 1)[1]) + b"\0" * (5 * 1024 * 1024)
        image["data_url"] = "data:image/png;base64," + base64.b64encode(raw).decode()
        self.assertEqual(self.send(images=[image]).status_code, 400)
        self.assertFalse(self.store.messages("alice", self.sid)["items"])

    def test_idempotent_retry_keeps_images_and_rejects_changed_image(self):
        request_id = str(uuid4())
        self.assertEqual(self.send(request_id=request_id).status_code, 200)
        image = self.saved_image()
        self.assertEqual(self.send(request_id=request_id).status_code, 200)
        self.assertEqual(self.send(images=[], request_id=request_id).status_code, 200)
        self.assertEqual(self.saved_image()["id"], image["id"])
        self.assertEqual(self.send(images=[self.image("blue")], request_id=request_id).status_code, 409)
        self.assertEqual(len([call for call in self.case.calls if call.get("stream")]), 1)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_images").fetchone()[0], 1)

    def test_failed_turn_can_retry_saved_images_without_uploading_again(self):
        calls = self.case.calls

        class BrokenClient(FakeClient):
            def create(inner, **kwargs):
                if kwargs.get("stream"):
                    raise RuntimeError("offline disconnect")
                return super().create(**kwargs)

        self.service.client_factory = lambda runtime: BrokenClient(calls)
        request_id = str(uuid4())
        self.assertIn('"type": "error"', self.send(request_id=request_id).text)
        image = self.saved_image()
        self.service.client_factory = lambda runtime: FakeClient(calls)
        self.assertIn('"type": "done"', self.send(images=[], request_id=request_id).text)
        self.assertEqual(self.saved_image()["id"], image["id"])
        self.assertEqual(len(calls[-1]["messages"][-1]["content"]), 2)

    def test_session_deletion_cascades_to_image_bytes(self):
        self.send()
        image = self.saved_image()
        self.assertEqual(self.case.api("DELETE", f"/api/chat/sessions/{self.sid}").status_code, 202)
        self.assertEqual(self.case.client.get(image["url"]).status_code, 404)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM chat_images").fetchone()[0], 0)

    def test_clear_chat_preserves_another_accounts_identical_image(self):
        self.send()
        alice_image = self.saved_image()
        self.case.login("bob")
        alice_sid, self.sid = self.sid, self.case.create()
        self.send()
        bob_image = self.store.messages("bob", self.sid)["items"][0]["images"][0]
        self.sid = alice_sid
        self.case.login("alice")
        self.assertEqual(self.case.api("DELETE", "/api/chat/chat-data").status_code, 202)
        self.assertEqual(self.case.client.get(alice_image["url"]).status_code, 404)
        self.case.login("bob")
        self.assertEqual(self.case.client.get(bob_image["url"]).status_code, 200)

    def test_forget_excludes_old_images_and_purge_removes_their_bytes(self):
        self.send(content="我希望去杭州工作。")
        image = self.saved_image()
        job, messages, result = self.case.batch(self.sid)
        self.service.memory.commit_candidates(job, messages, result["memories"], 0)
        memory = self.store.memory_snapshot("alice")[1][0]
        self.store.forget("alice", memory["id"])
        self.case.send(self.sid, "现在讨论别的问题。")
        trace = self.store.context_trace("alice", self.sid)
        self.assertEqual(trace["image_count"], 0)
        self.assertEqual(self.case.client.get(image["url"]).status_code, 200)
        self.store.request_memory_deletion("alice", memory["id"], mode="purge")
        self.assertEqual(self.case.client.get(image["url"]).status_code, 404)

    def test_visual_history_is_bounded_to_six_recent_images(self):
        for _ in range(7):
            self.assertEqual(self.send().status_code, 200)
        call = next(call for call in reversed(self.case.calls) if call.get("stream"))
        count = sum(part["type"] == "image_url" for message in call["messages"]
                    if isinstance(message["content"], list) for part in message["content"])
        self.assertEqual(count, 6)
        self.assertEqual(self.store.context_trace("alice", self.sid)["image_count"], 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
