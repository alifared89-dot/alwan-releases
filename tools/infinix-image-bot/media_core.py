#!/usr/bin/env python3
"""Brand-neutral media acquisition foundation. No handset vendor is hard-coded.

SourcePolicy is supplied by per-brand adapters; HTTPS, allowed hosts, payload
limits, redirects, and retry policy are enforced before fetching private data.
No publishing, device catalog assumptions, or external service credentials.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

TRANSIENT = frozenset({429, 502, 503, 504})
RETRY_LIMIT = 2
MAX_RETRY_DELAY = 6.0
MIN_HOST_INTERVAL = 0.12


@dataclass(frozen=True)
class SourcePolicy:
    brand: str
    hosts: frozenset[str]
    user_agent: str
    min_interval: float = MIN_HOST_INTERVAL

    def __post_init__(self):
        if not self.brand or not self.hosts or self.min_interval < 0:
            raise ValueError("invalid source policy")
        if any(not host or any(c in host for c in ":/@ ") for host in self.hosts):
            raise ValueError("host allowlist must contain DNS hostnames only")

    def require(self, url: str, expected_host: str) -> None:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != expected_host
                or parts.username is not None or parts.password is not None
                or parts.port is not None or expected_host not in self.hosts):
            raise ValueError("untrusted source URL / brand host")


class SourceUnavailable(RuntimeError):
    """Official service requires a pause or fails with non-retriable response."""


class NoRedirect(HTTPRedirectHandler):
    # Deny all automatic redirects; no external host is contacted before check.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(NoRedirect())
_LOCK = threading.RLock()
_NEXT_ALLOWED: dict[str, float] = {}
_BLOCKED_UNTIL: dict[str, float] = {}


def _retry_delay(exc: HTTPError, attempt: int) -> float:
    raw = (exc.headers.get("Retry-After") if exc.headers else None) or ""
    if raw:
        try:
            return max(0.0, float(raw.strip()))
        except ValueError:
            try:
                target = parsedate_to_datetime(raw)
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return 0.8 * (2 ** attempt)


def fetch_https(url: str, limit: int, expected_host: str, policy: SourcePolicy,
                *, timeout: int = 18, opener=None,
                clock=time.monotonic, sleep=time.sleep) -> tuple[bytes, str]:
    """Bounded GET with per-host pacing and HTTP transient retry limits.

    For 403 never retry. For 429 obey Retry-After only if short; otherwise
    fail gracefully without sleeping for minutes or hammering the source.
    Default no-redirect opener protects the destination allowlist before I/O.
    """
    policy.require(url, expected_host)
    if not 0 < limit <= 10_000_000:
        raise ValueError("unsafe network payload limit")
    open_url = opener or _OPENER.open
    req = Request(url, headers={"User-Agent": policy.user_agent,
                                "Accept": "application/json, text/html, image/*, */*"})
    for attempt in range(RETRY_LIMIT + 1):
        with _LOCK:
            now = clock()
            if now < _BLOCKED_UNTIL.get(expected_host, 0):
                raise SourceUnavailable("host temporarily paused after 403/429")
            delay = max(0.0, _NEXT_ALLOWED.get(expected_host, 0) - now)
            if delay:
                sleep(delay)
            _NEXT_ALLOWED[expected_host] = clock() + policy.min_interval
        try:
            with open_url(req, timeout=timeout) as response:
                destination = response.geturl()
                policy.require(destination, expected_host)
                if response.status != 200:
                    raise SourceUnavailable(f"official source returned {response.status}")
                payload = response.read(limit + 1)
            if len(payload) > limit:
                raise ValueError("source exceeds allowed download bytes")
            return payload, destination
        except HTTPError as exc:
            try:
                code = exc.code
                if code == 403:
                    with _LOCK:
                        _BLOCKED_UNTIL[expected_host] = clock() + 60
                    raise SourceUnavailable("403: official source refused access") from exc
                if code not in TRANSIENT:
                    raise
                wait = _retry_delay(exc, attempt)
                if wait > MAX_RETRY_DELAY:
                    with _LOCK:
                        _BLOCKED_UNTIL[expected_host] = clock() + wait
                    raise SourceUnavailable("source Retry-After exceeds bounded wait") from exc
                if attempt >= RETRY_LIMIT:
                    if code == 429:
                        with _LOCK:
                            _BLOCKED_UNTIL[expected_host] = clock() + max(wait, 1)
                    raise SourceUnavailable(f"source temporarily unavailable ({code})") from exc
            finally:
                exc.close()
            sleep(wait)
    raise RuntimeError("unreachable retry loop")


def reset_session_state_for_tests() -> None:
    """Only for isolated, deterministic unit tests; no production cache changes."""
    with _LOCK:
        _NEXT_ALLOWED.clear()
        _BLOCKED_UNTIL.clear()
