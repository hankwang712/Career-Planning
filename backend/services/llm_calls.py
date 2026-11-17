"""调用 OpenAI 兼容接口的共用函数：瞬态错误退避重试、结构化 JSON 解析与修复。"""
import json
import os
import random
import re
import time
import urllib.parse

from openai import OpenAI

CAREER_REPORT_LLM_TIMEOUT_SECONDS = max(
    30,
    int(os.environ.get("CAREER_REPORT_LLM_TIMEOUT_SECONDS", "180")),
)


def normalize_sdk_base_url(base_url):
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url 必须是完整的 http(s) 地址")
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]
    if cleaned.endswith("/v1"):
        return cleaned
    return f"{cleaned}/v1"


def extract_json_object(text):
    if not text:
        raise ValueError("模型没有返回可解析内容。")
    cleaned = str(text).strip()
    # 兼容 ```json ... ``` 包裹输出。
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        raise ValueError("模型返回中没有可解析的 JSON 对象。")
    return match.group(0)


def parse_structured_json(content):
    raw = str(content or "").strip()
    if not raw:
        raise ValueError("模型没有返回可解析内容。")
    # 1) 直接按 JSON 解析。
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 2) 提取 JSON 对象后再解析。
    extracted = extract_json_object(raw)
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        # 3) 本地轻度修复：去掉对象/数组尾逗号后再试。
        repaired = re.sub(r",(\s*[}\]])", r"\1", extracted)
        return json.loads(repaired)


# 网络级瞬态错误关键字，命中则触发重试（不含业务错误如鉴权失败）。
TRANSIENT_ERROR_KEYWORDS = (
    "connection", "timeout", "timed out", "reset", "broken pipe",
    "eof", "remote end closed", "server disconnected", "read timeout",
    "connect timeout", "service unavailable", "502", "503", "504",
    "overloaded", "rate limit", "too many requests", "429",
)


def is_transient_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in TRANSIENT_ERROR_KEYWORDS)


def safe_create_chat_completion(
    client, model, messages, temperature, max_tokens,
    force_json=False,
    max_retries=3,
    base_delay=1.5,
):
    """
    调用 chat.completions.create，对瞬态网络错误做指数退避重试。
    - max_retries: 最多额外重试次数（首次调用不计）
    - base_delay:  首次重试前的基础等待秒数，每次翻倍并加随机抖动
    """
    kwargs = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if force_json:
        kwargs["response_format"] = {"type": "json_object"}

    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()

            # response_format 不兼容 — 只重试一次，不计入重试次数
            if force_json and ("response_format" in msg or "json_object" in msg):
                kwargs.pop("response_format", None)
                try:
                    return client.chat.completions.create(**kwargs)
                except Exception as exc2:
                    last_exc = exc2
                    msg = str(exc2).lower()

            # 非瞬态错误（如鉴权、模型不存在）直接抛出，不重试
            if not is_transient_error(last_exc):
                raise

            # 最后一次也失败了
            if attempt >= max_retries:
                break

            delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.8)
            time.sleep(delay)

    raise last_exc


def call_structured_chat(base_url, api_key, model, messages, system_prompt, max_tokens=480,
                          max_retries=3, base_delay=1.5):
    base = normalize_sdk_base_url(base_url)
    client = OpenAI(
        api_key=api_key,
        base_url=base,
        timeout=CAREER_REPORT_LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    try:
        merged_messages = [{"role": "system", "content": system_prompt}] + messages
        resp = safe_create_chat_completion(
            client=client,
            model=model,
            messages=merged_messages,
            temperature=0.1,
            max_tokens=max_tokens,
            force_json=True,
            max_retries=max_retries,
            base_delay=base_delay,
        )
    except Exception as exc:
        raise ValueError(f"LLM 接口调用失败: {str(exc)[:300]}") from exc

    content = str((resp.choices[0].message.content or "") if resp.choices else "").strip()
    if not content:
        raise ValueError("模型没有返回可解析内容。")
    try:
        return parse_structured_json(content)
    except Exception:
        # 第一次失败：让模型只做 JSON 修复，不做新推理。
        repair_prompt = (
            "你是 JSON 修复器。请把下面的文本修复为严格合法的 JSON 对象。"
            "只能输出 JSON 对象本身，不要解释，不要 Markdown。"
        )
        repair_messages = [
            {"role": "system", "content": repair_prompt},
            {"role": "user", "content": content},
        ]
        try:
            repair_resp = safe_create_chat_completion(
                client=client,
                model=model,
                messages=repair_messages,
                temperature=0,
                max_tokens=min(max_tokens + 600, 3800),
                force_json=True,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            repair_content = str((repair_resp.choices[0].message.content or "") if repair_resp.choices else "").strip()
            return parse_structured_json(repair_content)
        except Exception:
            pass

        # 第二次失败：重新生成，并附加强约束和更高 token 上限。
        strict_system = (
            system_prompt
            + "\n\n严格要求：必须返回合法 JSON 对象。"
            + "不要输出注释、代码块、尾逗号或未转义换行。"
        )
        retry_messages = [{"role": "system", "content": strict_system}] + messages
        try:
            retry_resp = safe_create_chat_completion(
                client=client,
                model=model,
                messages=retry_messages,
                temperature=0.05,
                max_tokens=min(max_tokens + 800, 4096),
                force_json=True,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            retry_content = str((retry_resp.choices[0].message.content or "") if retry_resp.choices else "").strip()
            return parse_structured_json(retry_content)
        except Exception as exc:
            raise ValueError(f"结构化 JSON 解析失败: {str(exc)[:280]}") from exc


def call_markdown_chat(base_url, api_key, model, messages, system_prompt=None, max_tokens=3200,
                        max_retries=3, base_delay=1.5):
    base = normalize_sdk_base_url(base_url)
    client = OpenAI(
        api_key=api_key,
        base_url=base,
        timeout=CAREER_REPORT_LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )
    merged_messages = list(messages or [])
    if system_prompt:
        merged_messages = [{"role": "system", "content": system_prompt}] + merged_messages
    try:
        resp = safe_create_chat_completion(
            client=client,
            model=model,
            messages=merged_messages,
            temperature=0.2,
            max_tokens=max_tokens,
            force_json=False,
            max_retries=max_retries,
            base_delay=base_delay,
        )
    except Exception as exc:
        raise ValueError(f"LLM 接口调用失败: {str(exc)[:300]}") from exc

    content = str((resp.choices[0].message.content or "") if resp.choices else "").strip()
    if not content:
        raise ValueError("模型没有返回可解析内容。")
    return content
