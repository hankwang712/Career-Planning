"""Bounded, anonymous previews of public links appearing in a user's report."""
from collections import OrderedDict
from html import unescape
from html.parser import HTMLParser
import http.client
import ipaddress
import re
import socket
import ssl
import threading
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit


_CACHE = OrderedDict()
_IMAGES = OrderedDict()
_LOCK = threading.Lock()
_SLOTS = threading.BoundedSemaphore(4)
_IMAGE_SLOTS = threading.BoundedSemaphore(2)


def public_preview_url(value):
    value = unescape(str(value or "").strip())
    if len(value) > 3000 or re.search(r"[\s\\\x00-\x1f]", value):
        return ""
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        if parsed.scheme not in {"http", "https"} or not host or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return ""
        if host.rstrip(".") == "localhost" or host.rstrip(".").endswith((".localhost", ".local", ".internal")):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        authority = f"[{host}]" if ":" in host else host
        if parsed.port is not None:
            authority += f":{parsed.port}"
        return urlunsplit((parsed.scheme, authority, quote(parsed.path or "/", safe="/%:@!$&'()*+,;=-._~"), quote(parsed.query, safe="/%?:@!$&'()*+,;=-._~[]"), ""))
    except (ValueError, UnicodeError):
        return ""


def report_contains_url(bundle, url, snapshot=None):
    wanted = public_preview_url(url)
    if not wanted:
        return False
    document = bundle.get("report_document") or {}
    texts = [document.get("markdown", "")]
    texts.extend(section.get("markdown", "") for section in document.get("sections", {}).values() if isinstance(section, dict))
    if snapshot:
        texts.append(snapshot.get("markdown", ""))
    for text in texts:
        for match in re.findall(r'https?://[^\s<>"\']+', str(text)):
            if wanted in {public_preview_url(match), public_preview_url(match.rstrip(").,，。；」》"))}:
                return True
    return False


def _fetch(url, *, image=False):
    """Pin each connection to a checked public IP, including every redirect."""
    deadline = time.monotonic() + 9
    limit = 1_000_000 if image else 300_000
    for _ in range(4):
        url = public_preview_url(url)
        if not url:
            raise ValueError("Invalid public link")
        parsed = urlsplit(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ValueError("Non-public address")
        remaining = min(4, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Preview deadline exceeded")
        connection = (http.client.HTTPSConnection(parsed.hostname, port, timeout=remaining, context=ssl.create_default_context())
                      if parsed.scheme == "https" else http.client.HTTPConnection(parsed.hostname, port, timeout=remaining))
        address = addresses[0][4][0]
        # Keep the real hostname for Host, certificate verification and SNI.
        connection._create_connection = lambda endpoint, timeout, source_address=None: socket.create_connection((address, port), timeout, source_address)
        try:
            connection.request("GET", urlunsplit(("", "", parsed.path or "/", parsed.query, "")), headers={
                "User-Agent": "Mozilla/5.0 CareerReportPreview/1.0", "Accept": "image/*" if image else "text/html,application/xhtml+xml", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.getheader("Location") or "")
                continue
            if response.status != 200 or response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Preview unavailable")
            content_type = response.getheader("Content-Type", "").lower()
            accepted = {"image/png", "image/jpeg", "image/webp", "image/gif"} if image else {"text/html", "application/xhtml+xml"}
            if content_type.split(";", 1)[0].strip() not in accepted:
                raise ValueError("Unsupported preview type")
            data = bytearray()
            while len(data) <= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Preview deadline exceeded")
                if connection.sock:
                    connection.sock.settimeout(min(4, remaining))
                chunk = response.read1(min(16384, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if not image and b"</head" in data[-16400:].lower():
                    break
            if len(data) > limit:
                if image:
                    raise ValueError("Preview too large")
                del data[limit:]
            return bytes(data), content_type, url
        finally:
            connection.close()
    raise ValueError("Too many redirects")


class MetadataParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.metadata = {}
        self.title = []
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key and values.get("content"):
                self.metadata.setdefault(key, values["content"])
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def parse_preview(data, content_type, url):
    charset = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type, re.I)
    if not charset:
        charset = re.search(rb"charset\s*=\s*['\"]?([\w-]+)", data[:4096], re.I)
    encoding = charset[1] if charset else "utf-8"
    if isinstance(encoding, bytes):
        encoding = encoding.decode("ascii", "ignore")
    try:
        html = data.decode(encoding, "replace")
    except LookupError:
        html = data.decode("utf-8", "replace")
    parser = MetadataParser()
    parser.feed(html)
    meta = parser.metadata
    clean = lambda value, length: re.sub(r"\s+", " ", re.sub(r"<[^>]*>", "", str(value or ""))).strip()[:length]
    title = clean(meta.get("og:title") or meta.get("twitter:title") or "".join(parser.title), 180)
    if re.search(r"^(?:just a moment|access denied|安全验证|访问受限|验证码)", title, re.I):
        raise ValueError("Page requires verification")
    image = meta.get("og:image:secure_url") or meta.get("og:image") or meta.get("twitter:image") or meta.get("twitter:image:src")
    return {"title": title, "description": clean(meta.get("og:description") or meta.get("description") or meta.get("twitter:description"), 360),
            "site_name": clean(meta.get("og:site_name"), 80), "image": public_preview_url(urljoin(url, image)) if image else ""}


def _cached(cache, key):
    with _LOCK:
        found = cache.get(key)
        if found and found[0] > time.monotonic():
            cache.move_to_end(key)
            return found[1]
        cache.pop(key, None)
    return None


def _save(cache, key, value, ttl, capacity):
    with _LOCK:
        cache[key] = (time.monotonic() + ttl, value)
        cache.move_to_end(key)
        while len(cache) > capacity:
            cache.popitem(last=False)


def get_link_preview(url):
    url = public_preview_url(url)
    if not url:
        raise ValueError("不支持此链接预览")
    cached = _cached(_CACHE, url)
    if cached is not None:
        return dict(cached)
    result = {"url": url, "domain": urlsplit(url).hostname, "title": "", "description": "", "site_name": "", "image": "", "status": "unavailable"}
    if not _SLOTS.acquire(timeout=1):
        return result
    try:
        data, content_type, final_url = _fetch(url)
        result.update(parse_preview(data, content_type, final_url))
        result["status"] = "ok" if result["title"] or result["description"] else "unavailable"
    except (OSError, ValueError, http.client.HTTPException):
        pass
    finally:
        _SLOTS.release()
    _save(_CACHE, url, dict(result), 21600 if result["status"] == "ok" else 600, 256)
    return result


def get_link_preview_image(url):
    image_url = get_link_preview(url).get("image")
    if not image_url:
        return None
    cached = _cached(_IMAGES, image_url)
    if cached is not None:
        return cached if cached is not False else None
    if not _IMAGE_SLOTS.acquire(timeout=4):
        return None
    try:
        data, content_type, _ = _fetch(image_url, image=True)
        mime = content_type.split(";", 1)[0].strip()
        signatures = {"image/png": data.startswith(b"\x89PNG\r\n\x1a\n"), "image/jpeg": data.startswith(b"\xff\xd8\xff"),
                      "image/gif": data.startswith((b"GIF87a", b"GIF89a")), "image/webp": data.startswith(b"RIFF") and data[8:12] == b"WEBP"}
        if not signatures.get(mime):
            raise ValueError("Invalid preview image")
        _save(_IMAGES, image_url, (data, mime), 21600, 24)
        return data, mime
    except (OSError, ValueError, http.client.HTTPException):
        _save(_IMAGES, image_url, False, 600, 24)
        return None
    finally:
        _IMAGE_SLOTS.release()
