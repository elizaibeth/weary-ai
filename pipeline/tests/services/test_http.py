import http.client
import urllib.error

import pytest

from agent.services import _http


def test_post_returns_body_on_first_success(monkeypatch):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    monkeypatch.setattr(_http.request, "urlopen", lambda req, timeout: _Resp())
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    assert _http.post("https://x", b"{}", {}, timeout=1) == b"ok"


def test_post_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"ok"

    def urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("https://x", 429, "rate limited", {}, None)
        return _Resp()

    monkeypatch.setattr(_http.request, "urlopen", urlopen)
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    assert _http.post("https://x", b"{}", {}, timeout=1) == b"ok"
    assert calls["n"] == 2


def test_post_does_not_retry_on_a_non_retryable_status(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError("https://x", 400, "bad request", {}, None)

    monkeypatch.setattr(_http.request, "urlopen", urlopen)
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    with pytest.raises(urllib.error.HTTPError):
        _http.post("https://x", b"{}", {}, timeout=1)


def test_post_retries_on_incomplete_read_then_gives_up(monkeypatch):
    def urlopen(req, timeout):
        raise http.client.IncompleteRead(b"partial")

    monkeypatch.setattr(_http.request, "urlopen", urlopen)
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    with pytest.raises(http.client.IncompleteRead):
        _http.post("https://x", b"{}", {}, timeout=1, retries=2)
