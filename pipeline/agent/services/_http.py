"""Shared HTTP POST helper with retry/backoff for the transient failures
real provider APIs actually produce: rate limiting, momentary 5xx, timeouts,
and truncated reads. Every provider client in this package goes through
here instead of calling `urllib.request` directly.
"""

import http.client
import time
import urllib.error
from urllib import request

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def post(url: str, payload: bytes, headers: dict, timeout: float, retries: int = 3) -> bytes:
    return _request(url, timeout, retries, data=payload, headers=headers, method="POST")


def get(url: str, headers: dict | None = None, timeout: float = 20, retries: int = 3) -> bytes:
    return _request(url, timeout, retries, data=None, headers=headers or {}, method="GET")


def _request(url: str, timeout: float, retries: int, **request_kwargs) -> bytes:
    for attempt in range(retries):
        try:
            req = request.Request(url, **request_kwargs)
            with request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in _RETRYABLE_STATUS or attempt == retries - 1:
                raise
        except (TimeoutError, http.client.IncompleteRead, urllib.error.URLError):
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt)
    raise AssertionError("unreachable")  # pragma: no cover
