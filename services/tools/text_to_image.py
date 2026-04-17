import json
import re
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_TEXT_TO_IMAGE_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TEXT_TO_IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"


def normalize_sdk_base_url(base_url):
    cleaned = (base_url or "").strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("base_url must be a full http(s) URL")
    if cleaned.endswith("/chat/completions"):
        cleaned = cleaned[: -len("/chat/completions")]
    if cleaned.endswith("/v1"):
        return cleaned
    return f"{cleaned}/v1"


def normalize_image_aspect_ratio(raw_value):
    cleaned = str(raw_value or "").strip()
    if re.fullmatch(r"\d{1,2}:\d{1,2}", cleaned):
        return cleaned
    return "1:1"


def extract_chat_message_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "text":
            continue
        text = str(item.get("text") or "").strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def get_text_to_image_runtime(payload=None, env_api_key="", default_base_url="", default_model="", providers=None):
    raw_payload = payload if isinstance(payload, dict) else {}
    base_url = str(raw_payload.get("base_url") or "").strip()
    api_key = str(raw_payload.get("api_key") or "").strip()
    model = str(raw_payload.get("model") or "").strip()
    resolved_base_url = default_base_url or DEFAULT_TEXT_TO_IMAGE_BASE_URL
    resolved_model = default_model or DEFAULT_TEXT_TO_IMAGE_MODEL

    if base_url and api_key:
        return base_url, api_key, model or resolved_model

    if env_api_key:
        return base_url or resolved_base_url, env_api_key, model or resolved_model

    provider_list = providers if isinstance(providers, list) else []
    provider = next(
        (
            item for item in provider_list
            if "openrouter.ai" in str(item.get("base_url") or "").strip().lower()
            and str(item.get("api_key") or "").strip()
        ),
        None,
    )
    if not provider:
        return base_url or resolved_base_url, "", model or resolved_model
    return (
        base_url or str(provider.get("base_url") or "").strip() or resolved_base_url,
        api_key or str(provider.get("api_key") or "").strip(),
        model or resolved_model,
    )


def generate_text_to_image(base_url, api_key, model, prompt, aspect_ratio="1:1"):
    safe_prompt = str(prompt or "").strip()
    if not safe_prompt:
        raise ValueError("prompt 不能为空。")
    if not base_url or not api_key:
        raise ValueError("未找到可用的 OpenRouter 图片配置，请传入 api_key 或先配置系统 Provider。")

    endpoint = f"{normalize_sdk_base_url(base_url)}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": safe_prompt}],
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": normalize_image_aspect_ratio(aspect_ratio)},
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(detail or "{}")
            message = str(parsed.get("error", {}).get("message") or parsed.get("message") or "").strip()
        except Exception:
            message = ""
        raise ValueError(message or f"图片接口调用失败，HTTP {exc.code}") from exc
    except Exception as exc:
        raise ValueError(f"图片接口调用失败：{str(exc)[:240]}") from exc

    try:
        result = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("图片接口返回了无法解析的数据。") from exc

    choices = result.get("choices") if isinstance(result, dict) else []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    images = message.get("images") if isinstance(message, dict) else []
    first_image = images[0] if images and isinstance(images[0], dict) else {}
    image_url_obj = first_image.get("image_url") if isinstance(first_image, dict) else {}
    image_url = str((image_url_obj or {}).get("url") or first_image.get("url") or "").strip()
    if not image_url:
        raise ValueError("模型没有返回图片结果。")
    return {
        "image_url": image_url,
        "mime_type": str((image_url_obj or {}).get("mime_type") or first_image.get("mime_type") or "").strip(),
        "text": extract_chat_message_text(message),
    }
