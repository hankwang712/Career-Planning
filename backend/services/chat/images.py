import base64
import binascii
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from .storage import ChatError

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_DATA_URL_LENGTH = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 128
MAX_MESSAGE_BODY = 22 * 1024 * 1024


def image_capability(runtime):
    """Known DeepSeek capabilities; other compatible providers validate remotely."""
    model = str(runtime[2] or "").lower()
    host = (urlsplit(runtime[0] or "").hostname or "").lower()
    if model.startswith("deepseek") or host == "api.deepseek.com":
        return model in {"deepseek-flash", "deepseek-v4-flash-vision-exp"}
    return None


def prepare_images(images):
    if len(images) > MAX_IMAGES:
        raise ChatError("每条消息最多发送 3 张图片。")
    prepared = []
    for item in images:
        match = re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=]+)", item["data_url"])
        if not match:
            raise ChatError("请选择 JPG、PNG、WebP 或 GIF 图片。")
        try:
            raw = base64.b64decode(match[1], validate=True)
        except (ValueError, binascii.Error):
            raise ChatError("图片编码无效，请重新选择。") from None
        if not raw or len(raw) > MAX_IMAGE_BYTES:
            raise ChatError("每张图片不能超过 5 MB。")
        try:
            with Image.open(BytesIO(raw)) as original:
                if original.format not in {"JPEG", "PNG", "WEBP", "GIF"} or original.width * original.height > 20_000_000:
                    raise ChatError("图片格式不支持或分辨率过大，请压缩后重试。")
                original.verify()
            with Image.open(BytesIO(raw)) as original:
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.thumbnail((2048, 2048))
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                output = BytesIO()
                background.save(output, format="PNG")
                mime = "image/png"
                if output.tell() > 3 * 1024 * 1024:
                    output = BytesIO()
                    background.save(output, format="JPEG", quality=88)
                    mime = "image/jpeg"
                name = Path(item.get("name", "图片").replace("\\", "/")).name
                name = "".join(char for char in name if char.isprintable())[:120] or "图片"
                prepared.append({"name": name, "mime": mime, "data": output.getvalue(),
                                 "width": background.width, "height": background.height})
        except ChatError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise ChatError("无法读取这张图片，请重新导出图片后上传。") from None
    return prepared


def model_parts(text, images):
    parts = [{"type": "text", "text": text}] if text else []
    parts.extend({"type": "image_url", "image_url": {"url": "data:" + image["mime"] + ";base64," +
                  base64.b64encode(image["data"]).decode("ascii")}} for image in images)
    return parts
