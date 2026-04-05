from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import ssl
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

WHATSAPP_INVITE_PATTERN = re.compile(
    r"(?:https?://)?chat\.whatsapp\.com/(?:invite/)?([A-Za-z0-9]{20,32})",
    re.IGNORECASE,
)
TELEGRAM_URL_PATTERN = re.compile(
    r"((?:https?://)?(?:(?:www\.)?(?:t|telegram)\.me)/[^\s<>'\"()]+)",
    re.IGNORECASE,
)
BLOCKED_TERM_PATTERNS = {
    "pornografi": re.compile(r"\b(?:bokep|porn|porno|sex|ngentot|jav|nsfw)\b", re.IGNORECASE),
    "minor": re.compile(r"\b(?:minor|underage|teen|remaja|anak sekolah)\b", re.IGNORECASE),
}

META_CONTENT_PATTERN = '<meta[^>]+property=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']'
ANCHOR_HREF_PATTERN = re.compile(r'<a\b[^>]+href=["\']([^"\']+)["\']', re.IGNORECASE)
SITE_OPERATOR_PATTERN = re.compile(r"\bsite:[^\s]+\b", re.IGNORECASE)
REDIRECT_WRAPPER_PATTERN = re.compile(r"/RU=([^/]+)/RK=", re.IGNORECASE)
SUPPORTED_PROVIDERS = ("duckduckgo", "brave", "yahoo", "aol", "google")
DEFAULT_ENABLED_PROVIDERS = ("duckduckgo", "yahoo", "aol", "brave")
DEFAULT_ENABLED_PROVIDERS_BY_PLATFORM = {
    "whatsapp": ("brave",),
    "telegram": DEFAULT_ENABLED_PROVIDERS,
}
SUPPORTED_PLATFORMS = ("whatsapp", "telegram")
SUPPORTED_DISCOVERY_MODES = ("focused", "wide")
DEFAULT_MAX_QUERY_WORKERS = 8
DEFAULT_MAX_QUERY_WORKERS_WHATSAPP_BRAVE = 2
DEFAULT_MAX_VALIDATION_WORKERS = 8
DEFAULT_FOLLOW_HOPS = 2
DEFAULT_MAX_FOLLOW_PAGES = 3
DEFAULT_MAX_FETCH_BUDGET = 200
DEFAULT_CACHE_DB_PATH = Path("crawler_cache.sqlite3")
DEFAULT_CACHE_TTL_HOURS = 72.0
PLATFORM_QUERY_TEMPLATES = {
    "whatsapp": "site:chat.whatsapp.com {keyword} whatsapp indonesia",
    "telegram": "site:t.me {keyword} telegram indonesia",
}
PLATFORM_DISCOVERY_CONFIG = {
    "whatsapp": {
        "invite_domain": "chat.whatsapp.com",
        "invite_marker": "chat.whatsapp.com",
        "platform_label": "whatsapp",
        "group_phrase": "grup whatsapp",
        "link_phrase": "link grup whatsapp",
    },
    "telegram": {
        "invite_domain": "t.me",
        "invite_marker": "t.me",
        "platform_label": "telegram",
        "group_phrase": "grup telegram",
        "link_phrase": "link grup telegram",
    },
}
DEFAULT_DISCOVERY_SOURCE_DOMAINS = (
    "ac.id",
    "or.id",
    "sch.id",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "reddit.com",
    "threads.net",
    "linktr.ee",
    "beacons.ai",
    "taplink.cc",
    "carrd.co",
    "blogspot.com",
    "wordpress.com",
    "medium.com",
    "notion.site",
    "kaskus.co.id",
    "kompasiana.com",
    "kumparan.com",
    "idntimes.com",
    "hipwee.com",
    "youngontop.com",
    "student-activity.binus.ac.id",
    "blog.ub.ac.id",
    "blog.ui.ac.id",
    "blog.unesa.ac.id",
    "blog.unnes.ac.id",
    "kemahasiswaan.ugm.ac.id",
    "kemahasiswaan.itb.ac.id",
    "kemahasiswaan.unair.ac.id",
)
DEFAULT_SHEET_WEBHOOK_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbzCBxIKA1jkxR4l0bQNtXUFWf-K5y7Qb8LDBtpTB_HRvMbee-uIOoWEg0LdJwkdu8hY/exec"
)
TELEGRAM_RESERVED_PATHS = {
    "addemoji",
    "addlist",
    "addstickers",
    "blog",
    "c",
    "faq",
    "games",
    "giftcode",
    "iv",
    "joinchat",
    "login",
    "proxy",
    "s",
    "setlanguage",
    "share",
    "share/url",
    "spam",
    "stickers",
    "telegrampassport",
}
SEARCH_PROVIDER_CONCURRENCY = {
    "duckduckgo": 4,
    "brave": 1,
    "yahoo": 4,
    "aol": 4,
    "google": 1,
}
SEARCH_PROVIDER_MIN_DELAY = {
    "brave": 3.0,
}
PROVIDER_FAILURE_THRESHOLD = {
    "brave": 2,
    "google": 3,
}
SEARCH_PROVIDER_SEMAPHORES = {
    provider: threading.Semaphore(SEARCH_PROVIDER_CONCURRENCY[provider])
    for provider in SUPPORTED_PROVIDERS
}
PROVIDER_FAILURE_COUNTS = {provider: 0 for provider in SUPPORTED_PROVIDERS}
DISABLED_PROVIDERS: set[str] = set()
PROVIDER_STATE_LOCK = threading.Lock()
DISALLOWED_UNICODE_RANGES = (
    "\u0600-\u06FF"  # Arabic
    "\u0750-\u077F"
    "\u08A0-\u08FF"
    "\u0900-\u097F"  # Devanagari
    "\u0980-\u09FF"  # Bengali
    "\u0A00-\u0A7F"  # Gurmukhi
    "\u0A80-\u0AFF"  # Gujarati
    "\u0B80-\u0BFF"  # Tamil
    "\u0C00-\u0C7F"  # Telugu
    "\u0C80-\u0CFF"  # Kannada
    "\u0D00-\u0D7F"  # Malayalam
    "\u0E00-\u0E7F"  # Thai
    "\u0E80-\u0EFF"  # Lao
    "\u1000-\u109F"  # Myanmar
    "\u1780-\u17FF"  # Khmer
    "\u3040-\u30FF"  # Japanese
    "\u3400-\u4DBF"
    "\u4E00-\u9FFF"  # Han
    "\uAC00-\uD7AF"  # Hangul
    "\u0400-\u04FF"  # Cyrillic
)
DISALLOWED_SCRIPT_PATTERN = re.compile(f"[{DISALLOWED_UNICODE_RANGES}]")
INDONESIA_TITLE_KEYWORDS = (
    "indonesia",
    "indo",
    "nusantara",
    "nasional",
    "warga",
    "anak muda",
    "muda",
    "pemuda",
    "mahasiswa",
    "kampus",
    "kuliah",
    "skripsi",
    "beasiswa",
    "magang",
    "rantau",
    "diskusi",
    "komunitas",
    "belajar",
    "bareng",
    "ngoding",
    "kerja",
    "lowongan",
    "loker",
    "karier",
    "bisnis",
    "wirausaha",
    "pengusaha",
    "usaha",
    "umkm",
    "online shop",
    "toko online",
    "reseller",
    "dropship",
    "affiliate",
    "creator",
    "kreator",
    "konten",
    "marketing",
    "pemasaran",
    "startup",
    "freelancer",
    "remote",
    "properti",
    "pertanian",
    "desain",
    "desainer",
    "digital",
    "chatgpt",
    "ai",
    "teknik informatika",
    "sistem informasi",
    "ilmu komputer",
    "universitas",
    "univ",
    "jakarta",
    "bandung",
    "jogja",
    "yogyakarta",
    "surabaya",
    "malang",
    "semarang",
    "medan",
    "makassar",
    "depok",
    "bogor",
    "bekasi",
    "ui",
    "itb",
    "ugm",
    "its",
    "unpad",
    "undip",
    "unair",
    "binus",
    "telkom",
    ".id",
    "id ",
)
NON_INDONESIA_TITLE_KEYWORDS = (
    "india",
    "pakistan",
    "arab",
    "saudi",
    "uae",
    "dubai",
    "qatar",
    "bangladesh",
    "nepal",
    "sri lanka",
    "egypt",
    "iraq",
    "iran",
    "afghanistan",
    "turkey",
    "turkiye",
    "philippines",
    "nigeria",
)
SEARCH_PROVIDER_EXCLUDED_HOSTS = {
    "yahoo": ("yahoo.com", "yimg.com", "aol.com", "oath.com"),
    "aol": ("aol.com", "yahoo.com", "yimg.com", "oath.com", "mapquest.com"),
}
FOLLOW_LINK_HINTS = {
    "whatsapp": (
        "chat.whatsapp.com",
        "whatsapp",
        "wa.me",
        "join",
        "grup",
        "group",
        "komunitas",
        "mahasiswa",
        "forum",
        "blog",
        "directory",
        "direktori",
    ),
    "telegram": (
        "t.me",
        "telegram",
        "join",
        "grup",
        "group",
        "komunitas",
        "mahasiswa",
        "forum",
        "blog",
        "directory",
        "direktori",
        "channel",
    ),
}
SKIPPED_FOLLOW_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".rar",
    ".7z",
    ".mp4",
    ".mp3",
    ".avi",
    ".mov",
    ".webm",
    ".css",
    ".js",
    ".json",
    ".xml",
)


@dataclass(frozen=True)
class GroupCheckResult:
    platform: str
    url: str
    status: str
    group_name: str | None = None
    member_count: int | None = None
    reason: str | None = None


class ProviderTemporarilyDisabledError(RuntimeError):
    pass


class FetchBudget:
    def __init__(self, max_requests: int | None) -> None:
        self.max_requests = max_requests if max_requests and max_requests > 0 else None
        self.used_requests = 0
        self._lock = threading.Lock()

    def try_acquire(self, count: int = 1) -> bool:
        if self.max_requests is None:
            return True
        with self._lock:
            if self.used_requests + count > self.max_requests:
                return False
            self.used_requests += count
            return True

    def remaining(self) -> int | None:
        if self.max_requests is None:
            return None
        with self._lock:
            return max(0, self.max_requests - self.used_requests)


class ValidationCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS validation_cache (
                    platform TEXT NOT NULL,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    group_name TEXT,
                    member_count INTEGER,
                    reason TEXT,
                    checked_at TEXT NOT NULL,
                    PRIMARY KEY (platform, url)
                )
                """
            )
            self._conn.commit()

    def get(self, platform: str, url: str, ttl_hours: float | None) -> GroupCheckResult | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT platform, url, status, group_name, member_count, reason, checked_at
                FROM validation_cache
                WHERE platform = ? AND url = ?
                """,
                (platform, url),
            ).fetchone()
        if row is None:
            return None
        if ttl_hours and ttl_hours > 0:
            try:
                checked_at = datetime.fromisoformat(str(row["checked_at"]))
            except ValueError:
                return None
            age_seconds = (datetime.now(timezone.utc) - checked_at).total_seconds()
            if age_seconds > ttl_hours * 3600:
                return None
        return GroupCheckResult(
            platform=str(row["platform"]),
            url=str(row["url"]),
            status=str(row["status"]),
            group_name=str(row["group_name"]) if row["group_name"] is not None else None,
            member_count=int(row["member_count"]) if row["member_count"] is not None else None,
            reason=str(row["reason"]) if row["reason"] is not None else None,
        )

    def put(self, result: GroupCheckResult) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO validation_cache (
                    platform, url, status, group_name, member_count, reason, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, url) DO UPDATE SET
                    status = excluded.status,
                    group_name = excluded.group_name,
                    member_count = excluded.member_count,
                    reason = excluded.reason,
                    checked_at = excluded.checked_at
                """,
                (
                    result.platform,
                    result.url,
                    result.status,
                    result.group_name,
                    result.member_count,
                    result.reason,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def normalize_title_text(text: str) -> str:
    lowered = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(lowered.split())


def is_probably_indonesian_group_name(group_name: str) -> bool:
    normalized = normalize_title_text(group_name)
    if not normalized:
        return False
    if DISALLOWED_SCRIPT_PATTERN.search(group_name):
        return False
    if any(keyword in normalized for keyword in NON_INDONESIA_TITLE_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in INDONESIA_TITLE_KEYWORDS)


def normalize_whatsapp_url(raw_url: str) -> str | None:
    match = WHATSAPP_INVITE_PATTERN.search(html.unescape(raw_url))
    if not match:
        return None
    return f"https://chat.whatsapp.com/{match.group(1)}"


def normalize_telegram_url(raw_url: str) -> str | None:
    text = html.unescape(raw_url).strip()
    match = TELEGRAM_URL_PATTERN.search(text)
    if not match:
        return None
    candidate = match.group(1)
    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate.lstrip('/')}"
    parsed = urllib.parse.urlparse(candidate)
    if not parsed.netloc.lower().endswith(("t.me", "telegram.me")):
        return None

    path = parsed.path.strip("/")
    if not path:
        return None
    parts = [part for part in path.split("/") if part]
    if not parts:
        return None

    first = parts[0]
    lowered_path = "/".join(parts[:2]).lower()
    if lowered_path in TELEGRAM_RESERVED_PATHS or first.lower() in TELEGRAM_RESERVED_PATHS:
        if first.lower() != "joinchat":
            return None

    if first.startswith("+"):
        invite_code = first[1:]
        if re.fullmatch(r"[A-Za-z0-9_-]{12,64}", invite_code):
            return f"https://t.me/+{invite_code}"
        return None

    if first.lower() == "joinchat" and len(parts) >= 2:
        invite_code = parts[1]
        if re.fullmatch(r"[A-Za-z0-9_-]{12,64}", invite_code):
            return f"https://t.me/joinchat/{invite_code}"
        return None

    handle = first
    if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", handle):
        return None
    return f"https://t.me/{handle}"


def normalize_group_url(raw_url: str, platform: str) -> str | None:
    if platform == "whatsapp":
        return normalize_whatsapp_url(raw_url)
    if platform == "telegram":
        return normalize_telegram_url(raw_url)
    raise ValueError(f"platform tidak didukung: {platform}")


def normalize_invite_url(raw_url: str) -> str | None:
    return normalize_whatsapp_url(raw_url)


def extract_group_links(text: str, platform: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    if platform == "whatsapp":
        for match in WHATSAPP_INVITE_PATTERN.finditer(html.unescape(text)):
            invite = normalize_whatsapp_url(match.group(0))
            if invite and invite not in seen:
                seen.add(invite)
                ordered.append(invite)
        return ordered
    if platform == "telegram":
        for match in TELEGRAM_URL_PATTERN.finditer(html.unescape(text)):
            link = normalize_telegram_url(match.group(1))
            if link and link not in seen:
                seen.add(link)
                ordered.append(link)
        return ordered
    raise ValueError(f"platform tidak didukung: {platform}")


def extract_invite_links(text: str) -> list[str]:
    return extract_group_links(text, "whatsapp")


def extract_duckduckgo_targets(search_html: str) -> list[str]:
    seen: set[str] = set()
    targets: list[str] = []
    for href in ANCHOR_HREF_PATTERN.findall(search_html):
        href = html.unescape(href)
        if href.startswith("//"):
            href = f"https:{href}"
        parsed = urllib.parse.urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("uddg", [""])[0]
        else:
            target = href
        if not target.startswith(("http://", "https://")):
            continue
        if target in seen:
            continue
        seen.add(target)
        targets.append(target)
    return targets


def extract_google_targets(search_html: str) -> list[str]:
    seen: set[str] = set()
    targets: list[str] = []
    for href in ANCHOR_HREF_PATTERN.findall(search_html):
        href = html.unescape(href)
        parsed = urllib.parse.urlparse(href)
        target = href
        if parsed.path == "/url":
            params = urllib.parse.parse_qs(parsed.query)
            target = params.get("q", params.get("url", [""]))[0]
        elif href.startswith("//"):
            target = f"https:{href}"
        if not target.startswith(("http://", "https://")):
            continue
        if "google." in urllib.parse.urlparse(target).netloc:
            continue
        if target in seen:
            continue
        seen.add(target)
        targets.append(target)
    return targets


def is_excluded_provider_host(host: str, excluded_hosts: tuple[str, ...]) -> bool:
    lowered = host.lower()
    return any(lowered == blocked or lowered.endswith(f".{blocked}") for blocked in excluded_hosts)


def extract_redirect_target(href: str) -> str:
    wrapper_match = REDIRECT_WRAPPER_PATTERN.search(href)
    if wrapper_match:
        return urllib.parse.unquote(wrapper_match.group(1))
    return href


def extract_yahoo_family_targets(search_html: str, excluded_hosts: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    targets: list[str] = []
    for href in ANCHOR_HREF_PATTERN.findall(search_html):
        href = html.unescape(href)
        if href.startswith("//"):
            href = f"https:{href}"
        target = extract_redirect_target(href)
        if not target.startswith(("http://", "https://")):
            continue
        host = urllib.parse.urlparse(target).netloc
        if is_excluded_provider_host(host, excluded_hosts):
            continue
        if target in seen:
            continue
        seen.add(target)
        targets.append(target)
    return targets


def extract_yahoo_targets(search_html: str) -> list[str]:
    return extract_yahoo_family_targets(search_html, SEARCH_PROVIDER_EXCLUDED_HOSTS["yahoo"])


def extract_aol_targets(search_html: str) -> list[str]:
    return extract_yahoo_family_targets(search_html, SEARCH_PROVIDER_EXCLUDED_HOSTS["aol"])


def resolve_brave_reference(
    value: object,
    table: list[object],
    cache: dict[int, object | None],
) -> object:
    if isinstance(value, int):
        if value == -1:
            return None
        if value < 0 or value >= len(table):
            return value
        if value in cache:
            return cache[value]
        cache[value] = None
        resolved = resolve_brave_reference(table[value], table, cache)
        cache[value] = resolved
        return resolved
    if isinstance(value, list):
        return [resolve_brave_reference(item, table, cache) for item in value]
    if isinstance(value, dict):
        return {
            key: resolve_brave_reference(item, table, cache)
            for key, item in value.items()
        }
    return value


def extract_brave_targets(search_payload: str) -> list[str]:
    parsed = json.loads(search_payload)
    if not isinstance(parsed, dict):
        return []
    nodes = parsed.get("nodes")
    if not isinstance(nodes, list) or len(nodes) < 2:
        return []
    node = nodes[1]
    if not isinstance(node, dict):
        return []
    table = node.get("data")
    if not isinstance(table, list):
        return []

    root = resolve_brave_reference(0, table, {})
    if not isinstance(root, dict):
        return []
    body = root.get("body")
    if not isinstance(body, dict):
        return []
    response = body.get("response")
    if not isinstance(response, dict):
        return []
    web = response.get("web")
    if not isinstance(web, dict):
        return []
    results = web.get("results")
    if not isinstance(results, list):
        return []

    seen: set[str] = set()
    targets: list[str] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        url = result.get("url")
        if not isinstance(url, str):
            continue
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        targets.append(url)
    return targets


def is_retryable_network_error(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionResetError, ssl.SSLError)):
        return True
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, (TimeoutError, ConnectionResetError, ssl.SSLError)):
            return True
        if "EOF occurred in violation of protocol" in str(reason):
            return True
    return "EOF occurred in violation of protocol" in str(exc)


def get_http_error_code(exc: Exception) -> int | None:
    if isinstance(exc, HTTPError):
        return exc.code
    if isinstance(exc, URLError) and isinstance(exc.reason, HTTPError):
        return exc.reason.code
    return None


def is_rate_limited_error(exc: Exception) -> bool:
    return get_http_error_code(exc) == 429


def reset_provider_runtime_state() -> None:
    with PROVIDER_STATE_LOCK:
        DISABLED_PROVIDERS.clear()
        for provider in SUPPORTED_PROVIDERS:
            PROVIDER_FAILURE_COUNTS[provider] = 0


def is_provider_disabled(provider: str) -> bool:
    with PROVIDER_STATE_LOCK:
        return provider in DISABLED_PROVIDERS


def mark_provider_failure(provider: str, exc: Exception) -> bool:
    threshold = PROVIDER_FAILURE_THRESHOLD.get(provider)
    if threshold is None:
        return False
    is_counted_failure = is_retryable_network_error(exc) or is_rate_limited_error(exc)
    if not is_counted_failure:
        return False
    with PROVIDER_STATE_LOCK:
        if provider in DISABLED_PROVIDERS:
            return True
        PROVIDER_FAILURE_COUNTS[provider] += 1
        if PROVIDER_FAILURE_COUNTS[provider] >= threshold:
            DISABLED_PROVIDERS.add(provider)
            return True
    return False


def mark_provider_success(provider: str) -> None:
    if provider not in PROVIDER_FAILURE_THRESHOLD:
        return
    with PROVIDER_STATE_LOCK:
        if provider not in DISABLED_PROVIDERS:
            PROVIDER_FAILURE_COUNTS[provider] = 0


def get_effective_search_delay(provider: str, delay_seconds: float) -> float:
    return max(delay_seconds, SEARCH_PROVIDER_MIN_DELAY.get(provider, 0.0))


def fetch_text(url: str, timeout: float, delay_seconds: float, retries: int = 0) -> str:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        sleep_seconds = delay_seconds if attempt == 0 else min(delay_seconds * (attempt + 1), 2.0)
        if sleep_seconds:
            time.sleep(sleep_seconds)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, "ignore")
        except Exception as exc:
            last_error = exc
            if attempt >= retries or not is_retryable_network_error(exc):
                raise
    assert last_error is not None
    raise last_error


def validate_term_safety(value: str) -> None:
    for category, pattern in BLOCKED_TERM_PATTERNS.items():
        if pattern.search(value):
            raise ValueError(
                f"term tidak didukung karena terkait {category}: {value!r}"
            )


def normalize_source_domain(value: str) -> str | None:
    cleaned = value.strip().lower()
    if not cleaned:
        return None
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urllib.parse.urlparse(cleaned)
    host = parsed.netloc or parsed.path
    host = host.strip().strip("/").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    return host


def resolve_discovery_source_domains(extra_domains: Iterable[str] | None = None) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()
    for domain in list(DEFAULT_DISCOVERY_SOURCE_DOMAINS) + list(extra_domains or []):
        normalized = normalize_source_domain(domain)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(normalized)
    return tuple(resolved)


def resolve_providers(platform: str, providers: Iterable[str] | None = None) -> list[str]:
    if providers:
        return list(dict.fromkeys(providers))
    return list(DEFAULT_ENABLED_PROVIDERS_BY_PLATFORM.get(platform, DEFAULT_ENABLED_PROVIDERS))


def resolve_max_query_workers(
    platform: str,
    providers: Iterable[str],
    query_count: int,
    requested_workers: int | None = None,
) -> int:
    if requested_workers:
        return max(1, requested_workers)
    default_workers = DEFAULT_MAX_QUERY_WORKERS
    normalized_providers = list(dict.fromkeys(providers))
    if platform == "whatsapp" and normalized_providers == ["brave"]:
        default_workers = DEFAULT_MAX_QUERY_WORKERS_WHATSAPP_BRAVE
    return max(1, min(query_count, default_workers))


def parse_member_count_token(value: str) -> int | None:
    raw_token = value.strip().lower()
    token = re.sub(r"\s+", "", raw_token).replace(",", ".")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([km]?)", token)
    if not match:
        digits = re.sub(r"\D", "", raw_token)
        return int(digits) if digits else None
    suffix = match.group(2)
    if not suffix:
        digits = re.sub(r"\D", "", raw_token)
        return int(digits) if digits else None
    number = float(match.group(1))
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    return int(number)


def extract_member_count_from_text(text: str, labels: tuple[str, ...]) -> int | None:
    lowered_labels = "|".join(re.escape(label) for label in labels)
    pattern = re.compile(
        rf"(\d[\d\s.,]*\d|\d+(?:[.,]\d+)?\s*[km]?)\s*(?:{lowered_labels})\b",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    return parse_member_count_token(match.group(1))


def is_http_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def normalize_follow_target(raw_href: str, base_url: str) -> str | None:
    href = html.unescape(raw_href).strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    target = urllib.parse.urljoin(base_url, href)
    target, _ = urllib.parse.urldefrag(target)
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    lowered_path = parsed.path.lower()
    if lowered_path.endswith(SKIPPED_FOLLOW_EXTENSIONS):
        return None
    return target


def score_follow_target(target_url: str, base_url: str, platform: str) -> int:
    target_parsed = urllib.parse.urlparse(target_url)
    base_parsed = urllib.parse.urlparse(base_url)
    target_host = target_parsed.netloc.lower()
    base_host = base_parsed.netloc.lower()
    combined = f"{target_host}{target_parsed.path.lower()}?{target_parsed.query.lower()}"
    score = 0
    if target_host == base_host:
        score += 4
    elif target_host.endswith(f".{base_host}") or base_host.endswith(f".{target_host}"):
        score += 3
    if target_host.endswith((".id", ".ac.id", ".or.id", ".sch.id", ".co.id")):
        score += 2
    if any(hint in combined for hint in FOLLOW_LINK_HINTS[platform]):
        score += 3
    if normalize_group_url(target_url, platform):
        score += 10
    return score


def extract_follow_targets(page_html: str, base_url: str, platform: str) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, href in enumerate(ANCHOR_HREF_PATTERN.findall(page_html)):
        target = normalize_follow_target(href, base_url)
        if not target or target in seen or target == base_url:
            continue
        if normalize_group_url(target, platform):
            continue
        seen.add(target)
        score = score_follow_target(target, base_url, platform)
        if score <= 0:
            continue
        ranked.append((score, index, target))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [target for _, _, target in ranked]


def build_keyword_discovery_queries(
    keyword: str,
    platform: str,
    discovery_mode: str,
    source_domains: Iterable[str] | None = None,
) -> list[str]:
    validate_term_safety(keyword)
    base_query = PLATFORM_QUERY_TEMPLATES[platform].format(keyword=keyword)
    if discovery_mode == "focused":
        return [base_query]

    config = PLATFORM_DISCOVERY_CONFIG[platform]
    normalized_domains = list(resolve_discovery_source_domains(source_domains))

    queries = [
        base_query,
        f'"{config["invite_marker"]}" {keyword} indonesia',
        f'"{config["group_phrase"]}" {keyword} indonesia',
        f'"{config["link_phrase"]}" {keyword} indonesia',
        f'{keyword} {config["platform_label"]} indonesia',
    ]
    queries.extend(
        f'site:{domain} "{config["invite_marker"]}" {keyword} indonesia'
        for domain in normalized_domains
    )

    unique: list[str] = []
    seen_queries: set[str] = set()
    for query in queries:
        if query not in seen_queries:
            seen_queries.add(query)
            unique.append(query)
    return unique


def expand_keywords_to_queries(
    keywords: list[str],
    platform: str,
    discovery_mode: str = "wide",
    source_domains: Iterable[str] | None = None,
) -> list[str]:
    queries: list[str] = []
    for keyword in keywords:
        queries.extend(
            build_keyword_discovery_queries(
                keyword,
                platform,
                discovery_mode=discovery_mode,
                source_domains=source_domains,
            )
        )
    return queries


def load_keywords(keyword_file: Path | None, cli_keywords: list[str]) -> list[str]:
    keywords: list[str] = []
    if keyword_file:
        for line in keyword_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                keywords.append(stripped)
    keywords.extend(keyword.strip() for keyword in cli_keywords if keyword.strip())
    unique: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            unique.append(keyword)
    return unique


def load_queries(
    platform: str,
    query_file: Path | None,
    cli_queries: list[str],
    keyword_file: Path | None,
    cli_keywords: list[str],
    discovery_mode: str = "wide",
    source_domains: Iterable[str] | None = None,
) -> list[str]:
    queries: list[str] = []
    if query_file:
        for line in query_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                validate_term_safety(stripped)
                queries.append(stripped)
    queries.extend(query.strip() for query in cli_queries if query.strip())
    for query in cli_queries:
        if query.strip():
            validate_term_safety(query)
    queries.extend(
        expand_keywords_to_queries(
            load_keywords(keyword_file, cli_keywords),
            platform,
            discovery_mode=discovery_mode,
            source_domains=source_domains,
        )
    )
    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        if query not in seen:
            seen.add(query)
            unique.append(query)
    return unique


def build_duckduckgo_search_url(query: str, page_index: int) -> str:
    params = {
        "q": query,
        "s": str(page_index * 30),
    }
    return f"https://html.duckduckgo.com/html/?{urllib.parse.urlencode(params)}"


def build_brave_search_url(query: str, page_index: int) -> str:
    params = {
        "q": query,
        "source": "web",
        "offset": str(page_index),
    }
    return f"https://search.brave.com/search/__data.json?{urllib.parse.urlencode(params)}"


def build_google_search_url(query: str, page_index: int) -> str:
    params = {
        "q": query,
        "num": "10",
        "hl": "en",
        "gbv": "1",
        "start": str(page_index * 10),
    }
    return f"https://www.google.com/search?{urllib.parse.urlencode(params)}"


def build_yahoo_search_url(query: str, page_index: int) -> str:
    params = {
        "p": query,
    }
    if page_index:
        params.update(
            {
                "b": str(page_index * 7 + 1),
                "pz": "7",
                "bct": "0",
                "xargs": "0",
            }
        )
    return f"https://search.yahoo.com/search?{urllib.parse.urlencode(params)}"


def build_aol_search_url(query: str, page_index: int) -> str:
    params = {
        "q": query,
        "ei": "UTF-8",
        "nojs": "1",
    }
    if page_index:
        params.update(
            {
                "b": str(page_index * 7 + 1),
                "pz": "7",
            }
        )
    return f"https://search.aol.com/aol/search?{urllib.parse.urlencode(params)}"


def adapt_query_for_provider(provider: str, query: str) -> str:
    if provider in {"brave", "google"}:
        adapted = SITE_OPERATOR_PATTERN.sub(" ", query)
        adapted = adapted.replace('"', " ")
        return " ".join(adapted.split())
    return query


def build_search_url(provider: str, query: str, page_index: int) -> str:
    if provider == "duckduckgo":
        return build_duckduckgo_search_url(query, page_index)
    if provider == "brave":
        return build_brave_search_url(query, page_index)
    if provider == "yahoo":
        return build_yahoo_search_url(query, page_index)
    if provider == "aol":
        return build_aol_search_url(query, page_index)
    if provider == "google":
        return build_google_search_url(query, page_index)
    raise ValueError(f"provider tidak didukung: {provider}")


def extract_provider_targets(provider: str, search_body: str) -> list[str]:
    if provider == "duckduckgo":
        return extract_duckduckgo_targets(search_body)
    if provider == "brave":
        return extract_brave_targets(search_body)
    if provider == "yahoo":
        return extract_yahoo_targets(search_body)
    if provider == "aol":
        return extract_aol_targets(search_body)
    if provider == "google":
        return extract_google_targets(search_body)
    return []


def fetch_search_body(
    provider: str,
    search_url: str,
    timeout: float,
    delay_seconds: float,
) -> str:
    if is_provider_disabled(provider):
        raise ProviderTemporarilyDisabledError(provider)
    retries = 0 if provider == "google" else 1
    effective_timeout = min(timeout, 5.0) if provider == "google" else timeout
    effective_delay = get_effective_search_delay(provider, delay_seconds)
    semaphore = SEARCH_PROVIDER_SEMAPHORES[provider]
    with semaphore:
        if is_provider_disabled(provider):
            raise ProviderTemporarilyDisabledError(provider)
        try:
            body = fetch_text(
                search_url,
                timeout=effective_timeout,
                delay_seconds=effective_delay,
                retries=retries,
            )
        except Exception as exc:
            disabled = mark_provider_failure(provider, exc)
            if disabled:
                print(
                    f"[warn] provider {provider} dinonaktifkan untuk sisa run setelah kegagalan berulang: {exc}",
                    file=sys.stderr,
                )
                raise ProviderTemporarilyDisabledError(provider) from exc
            raise
        mark_provider_success(provider)
        return body


def collect_group_links_from_page(
    page_url: str,
    page_html: str,
    platform: str,
    timeout: float,
    delay_seconds: float,
    max_follow_hops: int,
    max_follow_pages: int,
    visited_pages: set[str],
    fetch_budget: FetchBudget | None = None,
) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    seen_links: set[str] = set()
    queue: deque[tuple[str, str, int]] = deque([(page_url, page_html, 0)])
    followed_pages = 0

    while queue:
        current_url, current_html, depth = queue.popleft()
        for link in extract_group_links(current_html, platform):
            if link in seen_links:
                continue
            seen_links.add(link)
            found.append((link, depth))
        if depth >= max_follow_hops:
            continue
        for target in extract_follow_targets(current_html, current_url, platform):
            if followed_pages >= max_follow_pages:
                break
            if target in visited_pages:
                continue
            if fetch_budget and not fetch_budget.try_acquire():
                break
            visited_pages.add(target)
            followed_pages += 1
            try:
                target_html = fetch_text(target, timeout=timeout, delay_seconds=delay_seconds)
            except Exception:
                continue
            queue.append((target, target_html, depth + 1))
    return found


def search_query_with_provider(
    platform: str,
    provider: str,
    query: str,
    timeout: float,
    delay_seconds: float,
    max_search_pages: int,
    max_result_pages: int,
    max_follow_hops: int,
    max_follow_pages: int,
    fetch_budget: FetchBudget | None = None,
) -> list[str]:
    candidate_scores: dict[str, int] = {}
    candidate_order: dict[str, int] = {}
    seen_targets: set[str] = set()
    visited_targets = 0
    provider_query = adapt_query_for_provider(provider, query)
    order_counter = 0

    def add_candidate(link: str, weight: int) -> None:
        nonlocal order_counter
        if link not in candidate_order:
            candidate_order[link] = order_counter
            order_counter += 1
        candidate_scores[link] = candidate_scores.get(link, 0) + weight

    for search_page_index in range(max_search_pages):
        if is_provider_disabled(provider):
            break
        search_url = build_search_url(provider, provider_query, search_page_index)
        try:
            search_body = fetch_search_body(
                provider=provider,
                search_url=search_url,
                timeout=timeout,
                delay_seconds=delay_seconds,
            )
        except ProviderTemporarilyDisabledError:
            break
        except Exception as exc:
            print(
                f"[warn] gagal mengambil hasil pencarian {provider}: {provider_query!r}: {exc}",
                file=sys.stderr,
            )
            continue

        for link in extract_group_links(search_body, platform):
            add_candidate(link, 6)

        targets = extract_provider_targets(provider, search_body)
        for target in targets:
            if visited_targets >= max_result_pages:
                break
            if target in seen_targets:
                continue
            if fetch_budget and not fetch_budget.try_acquire():
                break
            seen_targets.add(target)
            visited_targets += 1
            try:
                page_html = fetch_text(target, timeout=timeout, delay_seconds=delay_seconds)
            except Exception:
                continue
            for link, depth in collect_group_links_from_page(
                target,
                page_html,
                platform,
                timeout=timeout,
                delay_seconds=delay_seconds,
                max_follow_hops=max_follow_hops,
                max_follow_pages=max_follow_pages,
                visited_pages=seen_targets,
                fetch_budget=fetch_budget,
            ):
                add_candidate(link, 4 if depth == 0 else 2)

    ranked_candidates = sorted(
        candidate_scores,
        key=lambda link: (-candidate_scores[link], candidate_order[link]),
    )
    return ranked_candidates


def search_query(
    platform: str,
    query: str,
    timeout: float,
    delay_seconds: float,
    max_search_pages: int,
    max_result_pages: int,
    max_follow_hops: int,
    max_follow_pages: int,
    fetch_budget: FetchBudget | None,
    providers: list[str],
) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    max_workers = max(1, min(len(providers), 4))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_provider = {
            executor.submit(
                search_query_with_provider,
                platform,
                provider,
                query,
                timeout,
                delay_seconds,
                max_search_pages,
                max_result_pages,
                max_follow_hops,
                max_follow_pages,
                fetch_budget,
            ): provider
            for provider in providers
        }
        for future in as_completed(future_to_provider):
            provider = future_to_provider[future]
            try:
                results[provider] = future.result()
            except Exception as exc:
                print(
                    f"[warn] provider {provider} gagal diproses untuk query {query!r}: {exc}",
                    file=sys.stderr,
                )
                results[provider] = []
    return results


def search_queries_concurrently(
    platform: str,
    queries: list[str],
    timeout: float,
    delay_seconds: float,
    max_search_pages: int,
    max_result_pages: int,
    max_follow_hops: int,
    max_follow_pages: int,
    fetch_budget: FetchBudget | None,
    providers: list[str],
    max_query_workers: int | None,
) -> dict[str, dict[str, list[str]]]:
    results: dict[str, dict[str, list[str]]] = {}
    if not queries:
        return results

    worker_count = max_query_workers or len(queries)
    worker_count = max(1, min(worker_count, len(queries)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_query = {
            executor.submit(
                search_query,
                platform,
                query,
                timeout,
                delay_seconds,
                max_search_pages,
                max_result_pages,
                max_follow_hops,
                max_follow_pages,
                fetch_budget,
                providers,
            ): query
            for query in queries
        }
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                results[query] = future.result()
            except Exception as exc:
                print(
                    f"[warn] query gagal diproses {query!r}: {exc}",
                    file=sys.stderr,
                )
                results[query] = {provider: [] for provider in providers}
    return results


def extract_meta_property(text: str, prop: str) -> str:
    pattern = re.compile(META_CONTENT_PATTERN.format(prop=re.escape(prop)), re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def extract_telegram_page_extra(text: str) -> str:
    match = re.search(r'<div class="tgme_page_extra">([^<]*)</div>', text, re.IGNORECASE)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def extract_whatsapp_member_count(page_html: str) -> int | None:
    description = extract_meta_property(page_html, "og:description")
    return (
        extract_member_count_from_text(description, ("participant", "participants", "member", "members"))
        or extract_member_count_from_text(page_html, ("participant", "participants", "member", "members"))
    )


def extract_telegram_member_count(description: str, extra: str) -> int | None:
    return (
        extract_member_count_from_text(extra, ("member", "members"))
        or extract_member_count_from_text(description, ("member", "members"))
    )


def validate_whatsapp_link(url: str, timeout: float, delay_seconds: float) -> GroupCheckResult:
    normalized = normalize_whatsapp_url(url)
    if not normalized:
        return GroupCheckResult(
            platform="whatsapp",
            url=url,
            status="invalid",
            reason="link bukan invite WhatsApp",
        )

    validation_url = f"{normalized}?_fb_noscript=1"
    try:
        page = fetch_text(validation_url, timeout=timeout, delay_seconds=delay_seconds)
    except Exception as exc:
        return GroupCheckResult(
            platform="whatsapp",
            url=normalized,
            status="error",
            reason=str(exc),
        )

    group_name = extract_meta_property(page, "og:title")
    member_count = extract_whatsapp_member_count(page)
    if group_name:
        return GroupCheckResult(
            platform="whatsapp",
            url=normalized,
            status="active",
            group_name=group_name,
            member_count=member_count,
        )
    return GroupCheckResult(
        platform="whatsapp",
        url=normalized,
        status="inactive",
        member_count=member_count,
        reason="metadata grup kosong",
    )


def validate_telegram_link(url: str, timeout: float, delay_seconds: float) -> GroupCheckResult:
    normalized = normalize_telegram_url(url)
    if not normalized:
        return GroupCheckResult(
            platform="telegram",
            url=url,
            status="invalid",
            reason="link bukan grup Telegram publik",
        )

    parsed = urllib.parse.urlparse(normalized)
    path = parsed.path.strip("/")
    if path.startswith("+") or path.lower().startswith("joinchat/"):
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="unsupported",
            reason="invite Telegram privat tidak bisa diverifikasi aktif dari web statis",
        )

    try:
        page = fetch_text(normalized, timeout=timeout, delay_seconds=delay_seconds)
    except Exception as exc:
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="error",
            reason=str(exc),
        )

    group_name = extract_meta_property(page, "og:title")
    description = extract_meta_property(page, "og:description")
    extra = extract_telegram_page_extra(page)
    member_count = extract_telegram_member_count(description, extra)
    generic_titles = {
        "Telegram – a new era of messaging",
        "Telegram Messenger",
        "Join group chat on Telegram",
    }
    if not group_name or group_name in generic_titles:
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="inactive",
            reason="halaman Telegram generik atau username tidak valid",
        )
    if re.search(r"\bsubscriber(?:s)?\b", extra, re.IGNORECASE):
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="inactive",
            member_count=member_count,
            reason="tautan Telegram ini channel, bukan grup",
        )
    if re.search(r"\bmember(?:s)?\b", extra, re.IGNORECASE):
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="active",
            group_name=group_name,
            member_count=member_count,
        )
    if description and "group" in description.lower():
        return GroupCheckResult(
            platform="telegram",
            url=normalized,
            status="active",
            group_name=group_name,
            member_count=member_count,
        )
    return GroupCheckResult(
        platform="telegram",
        url=normalized,
        status="inactive",
        member_count=member_count,
        reason="halaman Telegram aktif tetapi tidak terdeteksi sebagai grup",
    )


def apply_indonesia_group_filter(result: GroupCheckResult, indonesia_only: bool) -> GroupCheckResult:
    if not indonesia_only or result.status != "active" or not result.group_name:
        return result
    if is_probably_indonesian_group_name(result.group_name):
        return result
    return GroupCheckResult(
        platform=result.platform,
        url=result.url,
        status="filtered",
        group_name=result.group_name,
        member_count=result.member_count,
        reason="nama grup tidak terindikasi Indonesia atau terdeteksi non-Indonesia",
    )


def apply_member_count_filter(result: GroupCheckResult, min_member_count: int | None) -> GroupCheckResult:
    if min_member_count is None or result.status != "active":
        return result
    if result.member_count is None:
        if result.platform == "whatsapp":
            return result
        return GroupCheckResult(
            platform=result.platform,
            url=result.url,
            status="filtered",
            group_name=result.group_name,
            member_count=result.member_count,
            reason=f"jumlah anggota tidak tersedia untuk filter minimum {min_member_count}",
        )
    if result.member_count >= min_member_count:
        return result
    return GroupCheckResult(
        platform=result.platform,
        url=result.url,
        status="filtered",
        group_name=result.group_name,
        member_count=result.member_count,
        reason=f"jumlah anggota {result.member_count} di bawah minimum {min_member_count}",
    )


def validate_group_link_raw(
    url: str,
    platform: str,
    timeout: float,
    delay_seconds: float,
    cache: ValidationCache | None = None,
    cache_ttl_hours: float | None = None,
) -> GroupCheckResult:
    cache_key = normalize_group_url(url, platform) or url.strip()
    if cache:
        cached = cache.get(platform, cache_key, cache_ttl_hours)
        if cached is not None:
            return cached
    if platform == "whatsapp":
        result = validate_whatsapp_link(url, timeout, delay_seconds)
    elif platform == "telegram":
        result = validate_telegram_link(url, timeout, delay_seconds)
    else:
        raise ValueError(f"platform tidak didukung: {platform}")
    if cache:
        cache.put(result)
    return result


def validate_group_link(
    url: str,
    platform: str,
    timeout: float,
    delay_seconds: float,
    indonesia_only: bool = True,
    min_member_count: int | None = None,
    cache: ValidationCache | None = None,
    cache_ttl_hours: float | None = None,
) -> GroupCheckResult:
    result = validate_group_link_raw(
        url,
        platform,
        timeout,
        delay_seconds,
        cache=cache,
        cache_ttl_hours=cache_ttl_hours,
    )
    result = apply_indonesia_group_filter(result, indonesia_only)
    return apply_member_count_filter(result, min_member_count)


def validate_invite(url: str, timeout: float, delay_seconds: float) -> GroupCheckResult:
    return validate_whatsapp_link(url, timeout, delay_seconds)


def load_saved_links(path: Path, platform: str = "whatsapp") -> list[str]:
    if not path.exists():
        return []
    links: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        normalized = normalize_group_url(line.strip(), platform)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        links.append(normalized)
    return links


def merge_unique_links(
    existing_links: Iterable[str],
    new_links: Iterable[str],
    platform: str = "whatsapp",
) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw_link in list(existing_links) + list(new_links):
        normalized = normalize_group_url(raw_link, platform)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


def save_links(
    path: Path,
    existing_links: Iterable[str],
    new_links: Iterable[str],
    platform: str = "whatsapp",
) -> tuple[int, int]:
    merged = merge_unique_links(existing_links, new_links, platform)
    existing_unique = merge_unique_links(existing_links, [], platform)
    new_count = max(0, len(merged) - len(existing_unique))
    content = "\n".join(merged)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return len(merged), new_count


def build_sheet_rows(results: list[GroupCheckResult]) -> list[dict[str, str]]:
    timestamp = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, str]] = []
    for result in results:
        rows.append(
            {
                "timestamp": timestamp,
                "platform": result.platform,
                "group_name": result.group_name or "",
                "url": result.url,
                "status": result.status,
                "member_count": result.member_count if result.member_count is not None else "",
            }
        )
    return rows


def sync_rows_to_sheet(sheet_webhook_url: str, rows: list[dict[str, str]], timeout: float) -> int:
    if not rows:
        return 0
    payload = json.dumps({"sheet": "Grup", "rows": rows}).encode("utf-8")
    request = urllib.request.Request(
        sheet_webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        response_body = response.read().decode(charset, "ignore")
    if not response_body.strip():
        return len(rows)
    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError:
        return len(rows)
    if isinstance(parsed, dict) and parsed.get("ok") is False:
        raise RuntimeError(str(parsed.get("error") or "sheet sync gagal"))
    if isinstance(parsed, dict) and isinstance(parsed.get("inserted"), int):
        return parsed["inserted"]
    return len(rows)


def validate_links_batch(
    links: list[str],
    platform: str,
    timeout: float,
    delay_seconds: float,
    indonesia_only: bool,
    min_member_count: int | None,
    max_workers: int,
    cache: ValidationCache | None = None,
    cache_ttl_hours: float | None = None,
) -> list[GroupCheckResult]:
    if not links:
        return []
    results: list[GroupCheckResult | None] = [None] * len(links)
    worker_count = max(1, min(max_workers, len(links)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_to_index = {
            executor.submit(
                validate_group_link,
                link,
                platform,
                timeout,
                delay_seconds,
                indonesia_only,
                min_member_count,
                cache,
                cache_ttl_hours,
            ): index
            for index, link in enumerate(links)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            link = links[index]
            try:
                results[index] = future.result()
            except Exception as exc:
                results[index] = GroupCheckResult(
                    platform=platform,
                    url=link,
                    status="error",
                    reason=str(exc),
                )
    return [result for result in results if result is not None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cari link grup WhatsApp atau Telegram publik, cek aktif/tidak, lalu simpan yang aktif."
    )
    parser.add_argument(
        "--platform",
        choices=SUPPORTED_PLATFORMS,
        default="whatsapp",
        help="Platform target: whatsapp atau telegram.",
    )
    parser.add_argument("--query-file", type=Path, help="File berisi satu query per baris.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Query tambahan. Bisa dipakai lebih dari sekali.",
    )
    parser.add_argument(
        "--keyword-file",
        type=Path,
        help="File berisi keyword dasar. Akan diubah menjadi query pencarian.",
    )
    parser.add_argument(
        "--keyword",
        action="append",
        default=[],
        help="Keyword tambahan. Bisa dipakai lebih dari sekali.",
    )
    parser.add_argument(
        "--discovery-mode",
        choices=SUPPORTED_DISCOVERY_MODES,
        default="wide",
        help="Mode pembentukan query dari keyword. 'wide' akan mencari ke banyak sumber publik seperti sosial media dan website.",
    )
    parser.add_argument(
        "--source-domain",
        action="append",
        default=[],
        help="Domain publik tambahan untuk discovery, misalnya facebook.com atau forumkampus.id. Bisa dipakai lebih dari sekali.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="File txt tujuan untuk link aktif. Kosongkan jika tidak ingin simpan file lokal.",
    )
    parser.add_argument(
        "--max-search-pages",
        type=int,
        default=1,
        help="Jumlah halaman hasil search per provider untuk setiap query.",
    )
    parser.add_argument(
        "--max-result-pages",
        type=int,
        default=10,
        help="Jumlah halaman hasil eksternal yang dirayapi per query.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout request dalam detik.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.0,
        help="Jeda antar request untuk mengurangi beban.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=SUPPORTED_PROVIDERS,
        help="Provider search. Default: semua provider aktif.",
    )
    parser.add_argument(
        "--max-query-workers",
        type=int,
        help=f"Jumlah worker paralel untuk query/keyword. Default dibatasi sampai {DEFAULT_MAX_QUERY_WORKERS}.",
    )
    parser.add_argument(
        "--max-validation-workers",
        type=int,
        default=DEFAULT_MAX_VALIDATION_WORKERS,
        help=f"Jumlah worker paralel untuk validasi grup. Default: {DEFAULT_MAX_VALIDATION_WORKERS}.",
    )
    parser.add_argument(
        "--follow-hops",
        type=int,
        default=DEFAULT_FOLLOW_HOPS,
        help=f"Jumlah hop tambahan dari halaman hasil. Default: {DEFAULT_FOLLOW_HOPS}.",
    )
    parser.add_argument(
        "--max-follow-pages",
        type=int,
        default=DEFAULT_MAX_FOLLOW_PAGES,
        help=f"Maksimal halaman lanjutan yang diikuti dari tiap halaman hasil. Default: {DEFAULT_MAX_FOLLOW_PAGES}.",
    )
    parser.add_argument(
        "--max-fetch-budget",
        type=int,
        default=DEFAULT_MAX_FETCH_BUDGET,
        help=f"Budget total fetch halaman target dan hop lanjutan per run. Default: {DEFAULT_MAX_FETCH_BUDGET}. Gunakan 0 untuk tanpa batas.",
    )
    parser.add_argument(
        "--sheet-webhook-url",
        default=DEFAULT_SHEET_WEBHOOK_URL,
        help="URL deploy Google Apps Script Web App untuk menulis hasil ke sheet tab 'Grup'.",
    )
    parser.add_argument(
        "--no-sheet-sync",
        action="store_true",
        help="Nonaktifkan sink default ke Google Sheets.",
    )
    parser.add_argument(
        "--max-active-groups",
        type=int,
        help="Berhenti setelah menemukan sejumlah grup aktif sesuai angka ini.",
    )
    parser.add_argument(
        "--min-member-count",
        type=int,
        default=50,
        help="Filter minimum jumlah anggota grup aktif. Gunakan 0 untuk mematikan filter. Default: 50.",
    )
    parser.add_argument(
        "--allow-global-groups",
        action="store_true",
        help="Matikan filter Indonesia-only pada nama grup.",
    )
    parser.add_argument(
        "--cache-db",
        type=Path,
        default=DEFAULT_CACHE_DB_PATH,
        help=f"Path file SQLite cache validasi. Default: {DEFAULT_CACHE_DB_PATH}.",
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=float,
        default=DEFAULT_CACHE_TTL_HOURS,
        help=f"Maksimum umur cache validasi dalam jam. Default: {DEFAULT_CACHE_TTL_HOURS}.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Matikan cache SQLite validasi lintas run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    output_path = args.output
    sheet_webhook_url = None if args.no_sheet_sync else args.sheet_webhook_url
    indonesia_only = not args.allow_global_groups
    min_member_count = args.min_member_count if args.min_member_count and args.min_member_count > 0 else None
    resolved_source_domains = resolve_discovery_source_domains(args.source_domain)
    max_validation_workers = max(1, args.max_validation_workers)
    follow_hops = max(0, args.follow_hops)
    max_follow_pages = max(0, args.max_follow_pages)
    fetch_budget = FetchBudget(args.max_fetch_budget)
    cache = None if args.no_cache else ValidationCache(args.cache_db)

    try:
        try:
            queries = load_queries(
                args.platform,
                args.query_file,
                args.query,
                args.keyword_file,
                args.keyword,
                discovery_mode=args.discovery_mode,
                source_domains=resolved_source_domains,
            )
        except ValueError as exc:
            parser.error(str(exc))
        if not queries:
            parser.error("Tidak ada query. Gunakan --query-file, --query, --keyword-file, atau --keyword.")
        if not output_path and not sheet_webhook_url:
            parser.error("Tidak ada sink hasil. Gunakan --output atau aktifkan sheet sync.")
        providers = resolve_providers(args.platform, args.provider)
        existing_links = load_saved_links(output_path, args.platform) if output_path else []
        existing_link_set = set(existing_links)
        max_query_workers = resolve_max_query_workers(
            args.platform,
            providers,
            len(queries),
            args.max_query_workers,
        )
        reset_provider_runtime_state()

        print(
            f"[info] platform: {args.platform}"
        )
        print(f"[info] mode discovery keyword: {args.discovery_mode}")
        print(f"[info] filter Indonesia-only: {indonesia_only}")
        print(f"[info] minimum anggota grup aktif: {min_member_count or 0}")
        if args.discovery_mode == "wide":
            source_domain_count = len(resolved_source_domains)
            print(f"[info] sumber publik tambahan untuk discovery: {source_domain_count} domain")
        print(
            f"[info] menjalankan {len(queries)} query dengan provider: {', '.join(providers)}"
        )
        print(f"[info] worker query paralel: {max_query_workers}")
        print(f"[info] worker validasi paralel: {max_validation_workers}")
        print(f"[info] follow hops: {follow_hops}, max follow pages: {max_follow_pages}")
        print(f"[info] fetch budget global: {args.max_fetch_budget if args.max_fetch_budget > 0 else 'unlimited'}")
        print(
            f"[info] cache validasi: {'mati' if args.no_cache else f'{args.cache_db} (ttl {args.cache_ttl_hours} jam)'}"
        )
        if existing_links:
            print(f"[info] link yang sudah ada di output akan dilewati: {len(existing_links)}")
        for index, query in enumerate(queries, start=1):
            print(f"[info] query siap {index}/{len(queries)}: {query}")

        query_results = search_queries_concurrently(
            platform=args.platform,
            queries=queries,
            timeout=args.timeout,
            delay_seconds=args.delay_seconds,
            max_search_pages=args.max_search_pages,
            max_result_pages=args.max_result_pages,
            max_follow_hops=follow_hops,
            max_follow_pages=max_follow_pages,
            fetch_budget=fetch_budget,
            providers=providers,
            max_query_workers=max_query_workers,
        )

        discovered: list[str] = []
        for query in queries:
            provider_results = query_results.get(query, {})
            print(f"[info] query selesai: {query}")
            query_links: list[str] = []
            for provider in providers:
                provider_links = provider_results.get(provider, [])
                print(f"[info] {provider}: kandidat ditemukan {len(provider_links)}")
                query_links.extend(provider_links)
            deduped_query_links = list(dict.fromkeys(query_links))
            print(f"[info] total kandidat unik per query: {len(deduped_query_links)}")
            discovered.extend(deduped_query_links)

        discovered_counter = Counter(discovered)
        first_seen_index: dict[str, int] = {}
        for index, link in enumerate(discovered):
            if link not in first_seen_index:
                first_seen_index[link] = index
        unique_discovered = sorted(
            discovered_counter,
            key=lambda link: (-discovered_counter[link], first_seen_index[link]),
        )
        print(f"[info] total kandidat unik: {len(unique_discovered)}")
        pending_links = [link for link in unique_discovered if link not in existing_link_set]
        print(f"[info] kandidat baru setelah filter output lama: {len(pending_links)}")

        active_results: list[GroupCheckResult] = []
        batch_size = max(1, max_validation_workers * 2)
        stop_validation = False
        for batch_start in range(0, len(pending_links), batch_size):
            batch_links = pending_links[batch_start:batch_start + batch_size]
            batch_results = validate_links_batch(
                batch_links,
                args.platform,
                timeout=args.timeout,
                delay_seconds=args.delay_seconds,
                indonesia_only=indonesia_only,
                min_member_count=min_member_count,
                max_workers=max_validation_workers,
                cache=cache,
                cache_ttl_hours=args.cache_ttl_hours,
            )
            for offset, result in enumerate(batch_results, start=batch_start + 1):
                if result.status == "active":
                    active_results.append(result)
                    member_count_text = f" [{result.member_count} anggota]" if result.member_count is not None else ""
                    print(
                        f"[ok] {offset}/{len(pending_links)} aktif: {result.group_name}{member_count_text} -> {result.url}"
                    )
                    if args.max_active_groups and len(active_results) >= args.max_active_groups:
                        print(f"[info] batas grup aktif tercapai: {args.max_active_groups}")
                        stop_validation = True
                        break
                elif result.status in {"inactive", "unsupported", "filtered"}:
                    print(
                        f"[skip] {offset}/{len(pending_links)} {result.status}: {result.url}"
                        + (f" ({result.reason})" if result.reason else "")
                    )
                else:
                    print(f"[warn] {offset}/{len(pending_links)} gagal cek: {result.url} ({result.reason})")
            if stop_validation:
                break

        if output_path:
            total_saved, new_saved = save_links(
                output_path,
                existing_links,
                [result.url for result in active_results],
                args.platform,
            )
            print(f"[info] link aktif baru tersimpan di file: {new_saved}")
            print(f"[info] total link unik di file output: {total_saved} -> {output_path}")
        else:
            print("[info] penyimpanan file lokal dimatikan")
        if sheet_webhook_url and active_results:
            try:
                inserted = sync_rows_to_sheet(
                    sheet_webhook_url,
                    build_sheet_rows(active_results),
                    timeout=max(args.timeout, 10.0),
                )
                print(f"[info] hasil aktif terkirim ke sheet tab Grup: {inserted}")
            except Exception as exc:
                print(f"[warn] gagal kirim ke sheet: {exc}", file=sys.stderr)
        remaining_budget = fetch_budget.remaining()
        if remaining_budget is not None:
            print(f"[info] sisa fetch budget global: {remaining_budget}")
        return 0
    finally:
        if cache is not None:
            cache.close()


if __name__ == "__main__":
    raise SystemExit(main())
