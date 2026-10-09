"""Calibre-Web-compatible author profile provider backed by Open Library.

This module intentionally keeps the public interface of Calibre-Web's
``cps/services/goodreads_support.py`` so it can replace that module in place.
"""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import markdown2
import nh3
import requests

API_ROOT = "https://openlibrary.org"
USER_AGENT = "CalibreWebOpenLibraryAuthorProvider/0.1 (+https://github.com/miguellobato84/calibre-web-overrides)"
REQUEST_TIMEOUT_SECONDS = 10
CACHE_TIMEOUT_SECONDS = 23 * 60 * 60
MIN_REQUEST_INTERVAL_SECONDS = 1.0
MAX_INLINE_PHOTO_BYTES = 512 * 1024

BIO_ALLOWED_TAGS = set(nh3.ALLOWED_TAGS) | {
    "p", "span", "div", "pre", "br", "h1", "h2", "h3", "h4", "h5", "h6", "code"
}
BIO_ALLOWED_ATTRIBUTES = {"a": {"href", "title"}}

log = logging.getLogger(__name__)
_cache: dict[str, tuple[float, AuthorInfo | None]] = {}
_cache_lock = threading.RLock()
_request_lock = threading.Lock()
_last_request_at = 0.0


@dataclass
class AuthorInfo:
    """Fields consumed by current Calibre-Web author templates/callers."""

    name: str
    image_url: str | None
    link: str
    about: str | None = None
    safe_about: str | None = None
    books: list[Any] = field(default_factory=list)
    gid: str | None = None
    birth_date: str | None = None
    death_date: str | None = None
    _timestamp: float = 0.0


def _normalize_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _throttle() -> None:
    global _last_request_at
    with _request_lock:
        now = time.monotonic()
        delay = MIN_REQUEST_INTERVAL_SECONDS - (now - _last_request_at)
        if delay > 0:
            time.sleep(delay)
        _last_request_at = time.monotonic()


def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    _throttle()
    response = requests.get(
        f"{API_ROOT}{path}",
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Open Library returned a non-object JSON response")
    return payload


def _author_id_from_key(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    author_id = key.rsplit("/", 1)[-1]
    return author_id if re.fullmatch(r"OL[0-9]+A", author_id) else None


def _find_author_id(author_name: str) -> str | None:
    search = _get_json(
        "/search/authors.json",
        {"q": author_name, "limit": 100, "fields": "key,name,alternate_names,work_count"},
    )
    candidates: dict[str, tuple[int, str]] = {}
    normalized_query = _normalize_name(author_name)
    for item in search.get("docs", []):
        if not isinstance(item, dict):
            continue
        alternate_names = item.get("alternate_names") or []
        if isinstance(alternate_names, str):
            alternate_names = [alternate_names]
        names = [item.get("name", ""), *alternate_names]
        if not any(
            isinstance(name, str) and _normalize_name(name) == normalized_query
            for name in names
        ):
            continue
        author_id = _author_id_from_key(item.get("key"))
        if not author_id:
            continue
        try:
            work_count = max(0, int(item.get("work_count", 0)))
        except (TypeError, ValueError):
            work_count = 0
        display_name = str(item.get("name", ""))
        candidates[author_id] = (max(work_count, candidates.get(author_id, (0, ""))[0]), display_name)

    if not candidates:
        log.info("No exact primary or alternate Open Library author match for %r", author_name)
        return None

    highest_work_count = max(work_count for work_count, _ in candidates.values())
    leaders = sorted(
        author_id for author_id, (work_count, _) in candidates.items()
        if work_count == highest_work_count
    )
    if len(leaders) != 1:
        log.warning(
            "Tied highest-work-count exact-name Open Library author results for %r (%s works): %s",
            author_name,
            highest_work_count,
            ", ".join(leaders),
        )
        return None
    if len(candidates) > 1:
        log.info(
            "Selected Open Library author %s for %r with highest work count (%s)",
            leaders[0],
            author_name,
            highest_work_count,
        )
    return leaders[0]


def _format_about(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    if not isinstance(value, str) or not value.strip():
        return None

    rendered = markdown2.markdown(value).strip()
    # The Calibre-Web author template wraps safe_about in a paragraph. Flatten
    # Markdown paragraph wrappers while keeping paragraph breaks readable.
    rendered = re.sub(r"</p>\s*<p>", "<br><br>", rendered, flags=re.IGNORECASE)
    rendered = re.sub(r"</?p>", "", rendered, flags=re.IGNORECASE)
    cleaned = nh3.clean(
        rendered,
        tags=BIO_ALLOWED_TAGS,
        attributes=BIO_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
    return cleaned.strip() or None


def _fetch_photo_data_url(photo_id: int) -> str | None:
    url = f"https://covers.openlibrary.org/a/id/{photo_id}-M.jpg?default=false"
    try:
        _throttle()
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "image/*"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            log.warning("Open Library photo %s returned non-image content", photo_id)
            return None
        if len(response.content) > MAX_INLINE_PHOTO_BYTES:
            log.warning("Open Library photo %s is too large to inline", photo_id)
            return None
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{content_type};base64,{encoded}"
    except requests.RequestException as exc:
        log.info("Open Library photo lookup failed for %s: %s", photo_id, exc)
        return None


def _build_author(author_name: str, author_id: str, record: dict[str, Any]) -> AuthorInfo:
    profile = f"{API_ROOT}/authors/{quote(author_id, safe='')}"
    photos = record.get("photos") or []
    photo_id = next((photo for photo in photos if isinstance(photo, int) and photo > 0), None)
    image_url = _fetch_photo_data_url(photo_id) if photo_id else None
    about = record.get("bio")
    if isinstance(about, dict):
        about = about.get("value")
    if not isinstance(about, str):
        about = None
    safe_about = _format_about(about)
    return AuthorInfo(
        name=author_name,
        image_url=image_url,
        link=profile,
        about=about,
        safe_about=safe_about,
        gid=author_id,
        birth_date=record.get("birth_date") if isinstance(record.get("birth_date"), str) else None,
        death_date=record.get("death_date") if isinstance(record.get("death_date"), str) else None,
        _timestamp=time.time(),
    )


def connect(key: str | None = None, enabled: bool = True) -> None:
    """Keep Calibre-Web's startup interface; Open Library is always enabled."""
    # Both legacy Goodreads arguments are accepted and deliberately ignored.
    # The caller may still gate whether it invokes this module at all.
    return None


def get_author_info(author_name: str) -> AuthorInfo | None:
    """Return the highest-work-count Open Library author result, or None on misses/errors."""
    if not isinstance(author_name, str) or not author_name.strip():
        return None

    cache_key = _normalize_name(author_name)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TIMEOUT_SECONDS:
            return cached[1]
        _cache.pop(cache_key, None)

    try:
        author_id = _find_author_id(author_name)
        if not author_id:
            with _cache_lock:
                _cache[cache_key] = (time.monotonic(), None)
            return None
        record = _get_json(f"/authors/{author_id}.json")
        author_info = _build_author(author_name, author_id, record)
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        log.warning("Open Library author lookup failed for %r: %s", author_name, exc)
        return None

    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), author_info)
    return author_info


def get_other_books(author_info: AuthorInfo | None, library_books: Any = None) -> list[Any]:
    """Keep Calibre-Web's interface; this provider supplies profiles only."""
    return []
