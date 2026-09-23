import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "X-IG-App-ID": "936619743392459",
    "Accept": "*/*",
}

RETRYABLE_EXCEPTIONS = (PermissionError, ConnectionRefusedError, requests.RequestException)


def parse_cookie_string(cookie_str: str) -> dict:
    """Parse common browser cookie formats into a requests cookie dictionary."""
    if not isinstance(cookie_str, str):
        return {}
    text = cookie_str.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()

    # Accept a pasted JSON browser export as well as the file-upload path.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(key): str(value) for key, value in parsed.items() if str(key)}
        if isinstance(parsed, list):
            return {
                str(item["name"]): str(item.get("value", ""))
                for item in parsed
                if isinstance(item, dict) and item.get("name")
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Netscape exports pasted directly into Telegram contain tab-separated
    # domain/metadata/name/value columns. Parse those before generic pairs.
    if "\t" in text:
        netscape = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7 and fields[5].strip() and fields[6].strip():
                netscape[fields[5].strip()] = fields[6].strip()
        if netscape:
            return netscape

    cookies = {}
    # Supports semicolons, newlines, commas, and whitespace between pairs:
    # sessionid=abc; ds_user_id=123, csrftoken=xyz
    parts = re.split(r";|\r?\n|,\s*(?=[A-Za-z0-9_.%-]+\s*=)|\s+(?=[A-Za-z0-9_.%-]+\s*=)", text)
    for item in parts:
        item = item.strip().lstrip("#HttpOnly_")
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            cookies[key] = value
    return cookies


def normalize_cookie_string(cookie_str: str) -> str:
    """Convert supported browser formats into a canonical Cookie header string."""
    cookies = parse_cookie_string(cookie_str)
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def validate_cookies(raw_cookies: str) -> dict:
    """Check whether Instagram accepts the session and return its current user."""
    cookies = parse_cookie_string(raw_cookies)
    if not cookies:
        raise ValueError("No cookies could be parsed")
    response = requests.get(
        "https://www.instagram.com/api/v1/accounts/current_user/",
        params={"edit": "true"},
        headers=HEADERS,
        cookies=cookies,
        timeout=20,
    )
    if response.status_code in (401, 403):
        raise PermissionError("Instagram rejected these cookies or the session has expired")
    if response.status_code == 429:
        raise ConnectionRefusedError("Instagram rate-limited the cookie check")
    response.raise_for_status()
    payload = response.json()
    user = payload.get("user") or payload.get("data", {}).get("user")
    if not user:
        raise PermissionError("Instagram did not return an authenticated user")
    return {
        "id": str(user.get("pk") or user.get("id") or ""),
        "username": user.get("username", "unknown"),
    }


def load_cookie_file(path: str) -> str:
    """Load raw, JSON, or Netscape-format cookies from a local file."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Cookie file is empty: {path}")

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return "; ".join(f"{key}={value}" for key, value in parsed.items())
        if isinstance(parsed, list):
            pairs = []
            for item in parsed:
                if isinstance(item, dict) and item.get("name"):
                    pairs.append(f"{item['name']}={item.get('value', '')}")
            if pairs:
                return "; ".join(pairs)
    except json.JSONDecodeError:
        pass

    # Netscape cookie export: domain, flag, path, secure, expiry, name, value.
    if "\t" in text and any(line and not line.startswith("#") for line in text.splitlines()):
        pairs = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7:
                pairs.append(f"{fields[5]}={fields[6]}")
        if pairs:
            return "; ".join(pairs)

    return text


def cookie_sources(primary: str = "", backup_values: list[str] | None = None) -> list[tuple[str, str]]:
    """Return primary plus three backup cookie sources, removing empty entries."""
    sources = []
    env_backups = [
        os.getenv("INSTAGRAM_COOKIES_BACKUP_1", ""),
        os.getenv("INSTAGRAM_COOKIES_BACKUP_2", ""),
        os.getenv("INSTAGRAM_COOKIES_BACKUP_3", ""),
    ]
    values = [
        ("primary", primary),
        ("backup-1", (backup_values or env_backups)[0]),
        ("backup-2", (backup_values or env_backups)[1]),
        ("backup-3", (backup_values or env_backups)[2]),
    ]
    for name, value in values:
        if value:
            candidate = value
            if os.path.isfile(candidate):
                candidate = load_cookie_file(candidate)
            if parse_cookie_string(candidate):
                sources.append((name, candidate))
    return sources


def normalize_username(value: str) -> str:
    value = value.strip()
    if "instagram.com" in value.lower():
        value = value.split("?", 1)[0].split("#", 1)[0].rstrip("/").split("/")[-1]
    return value.lstrip("@").strip().lower()


def _request(url: str, raw_cookies: str, params: dict | None = None) -> requests.Response:
    username = normalize_username(params.get("username", "")) if params else ""
    headers = HEADERS.copy()
    if username:
        headers["Referer"] = f"https://www.instagram.com/{username}/"
    response = requests.get(
        url,
        params=params,
        headers=headers,
        cookies=parse_cookie_string(raw_cookies),
        timeout=20,
    )
    if response.status_code in (401, 403):
        raise PermissionError("Cookies expired or invalid")
    if response.status_code == 429:
        raise ConnectionRefusedError("Instagram rate limit encountered")
    if response.status_code == 404:
        raise ValueError("Instagram profile or media not found")
    response.raise_for_status()
    return response


def get_profile_data(username: str, raw_cookies: str) -> dict:
    username = normalize_username(username)
    url = "https://www.instagram.com/api/v1/users/web_profile_info/"
    response = _request(url, raw_cookies, {"username": username})
    user_info = response.json().get("data", {}).get("user")
    if not user_info:
        raise ValueError("Profile payload empty (possible username change)")
    return {
        "id": str(user_info.get("id", "")),
        "username": user_info.get("username", username),
        "followers": int(user_info.get("edge_followed_by", {}).get("count", 0)),
        "profile": user_info,
    }


def get_profile_data_with_failover(username: str, sources: list[tuple[str, str]]) -> tuple[dict, str]:
    errors = []
    for name, cookies in sources:
        try:
            return get_profile_data(username, cookies), name
        except RETRYABLE_EXCEPTIONS as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("All cookie sources failed: " + " | ".join(errors))


def _caption(item: dict) -> str:
    caption = item.get("caption") or {}
    if isinstance(caption, dict):
        return str(caption.get("text", ""))
    return str(caption or "")


def _media_url(item: dict) -> str:
    candidates = item.get("video_versions") or item.get("video_versions2") or []
    if candidates:
        return candidates[0].get("url", "")
    image_versions = (item.get("image_versions2") or {}).get("candidates", [])
    if image_versions:
        return image_versions[0].get("url", "")
    return ""


def _media_type(item: dict) -> str:
    if item.get("media_type") == 2 or item.get("video_versions") or item.get("video_versions2"):
        return "video/reel"
    if item.get("carousel_media"):
        return "carousel"
    return "image/post"


def _item_to_record(item: dict, username: str) -> dict | None:
    media_url = _media_url(item)
    code = item.get("code") or item.get("shortcode") or ""
    if not media_url or not code:
        return None
    likes = int(item.get("like_count") or 0)
    comments = int(item.get("comment_count") or 0)
    plays = int(item.get("play_count") or item.get("video_view_count") or 0)
    return {
        "username": username,
        "caption": _caption(item),
        "media_url": media_url,
        "original_post_url": f"https://www.instagram.com/p/{code}/",
        "engagements": likes + comments + plays,
        "likes": likes,
        "comments": comments,
        "plays": plays,
        "duration": float(item.get("video_duration") or 0),
        "date_posting": item.get("taken_at") or item.get("taken_at_timestamp") or "",
        "media_type": _media_type(item),
    }


def collect_media(username_or_link: str, limit: int, raw_cookies: str) -> list[dict]:
    """Collect up to limit profile posts, videos, and reels through the web feed endpoint."""
    username = normalize_username(username_or_link)
    if limit < 1:
        raise ValueError("limit must be at least 1")
    profile = get_profile_data(username, raw_cookies)
    user_id = profile["id"]
    if not user_id:
        raise ValueError("Instagram did not return a user id")

    records = []
    max_id = None
    seen = set()
    while len(records) < limit:
        params = {"count": min(50, limit - len(records))}
        if max_id:
            params["max_id"] = max_id
        response = _request(f"https://www.instagram.com/api/v1/feed/user/{quote(user_id)}/", raw_cookies, params)
        payload = response.json()
        items = payload.get("items", [])
        if not items:
            break
        for item in items:
            record = _item_to_record(item, username)
            if record and record["original_post_url"] not in seen:
                seen.add(record["original_post_url"])
                records.append(record)
                if len(records) >= limit:
                    break
        max_id = payload.get("next_max_id")
        if not max_id or not payload.get("more_available", False):
            break
    return records


def collect_media_with_failover(username_or_link: str, limit: int, sources: list[tuple[str, str]]) -> tuple[list[dict], str]:
    errors = []
    for name, cookies in sources:
        try:
            return collect_media(username_or_link, limit, cookies), name
        except RETRYABLE_EXCEPTIONS as exc:
            errors.append(f"{name}: {exc}")
    raise RuntimeError("All cookie sources failed: " + " | ".join(errors))


def download_media(url: str, raw_cookies: str, destination: str) -> None:
    with requests.get(url, headers=HEADERS, cookies=parse_cookie_string(raw_cookies), timeout=60, stream=True) as response:
        response.raise_for_status()
        with open(destination, "wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
