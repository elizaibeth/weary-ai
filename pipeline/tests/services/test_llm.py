import json
import urllib.error

import pytest

from agent.services import costs, llm


def _fake_post(content: str, usage: dict, cost: float | None = None):
    def fake_post(url, payload, headers, timeout):
        assert url == "https://api.runware.ai/v1"
        body = json.loads(payload)
        assert body[0]["taskType"] == "textInference"
        result = {"text": content, "usage": usage}
        if cost is not None:
            result["cost"] = cost
        return json.dumps({"data": [result]}).encode()

    return fake_post


def test_complete_returns_the_generated_text(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr(
        "agent.services.llm._http.post",
        _fake_post("hello", {"promptTokens": 10, "completionTokens": 5}),
    )
    assert llm.complete("a prompt") == "hello"


def test_complete_sends_the_requested_model(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen["model"] = json.loads(payload)[0]["model"]
        return json.dumps({"data": [{"text": "x", "usage": {}}]}).encode()

    monkeypatch.setattr("agent.services.llm._http.post", fake_post)
    llm.complete("a prompt", model="some:other@model")
    assert seen["model"] == "some:other@model"


def test_complete_records_token_usage_and_dollar_cost(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr(
        "agent.services.llm._http.post",
        _fake_post("hello", {"promptTokens": 10, "completionTokens": 5}, cost=0.00042),
    )
    with costs.tracking() as run:
        llm.complete("a prompt")
    assert run.text_prompt_tokens == 10
    assert run.text_completion_tokens == 5
    assert run.text_usd == 0.00042


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.runware.ai/v1", code, "err", {}, None)


def test_complete_falls_back_to_the_fallback_model_on_a_502(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    seen_models = []

    def fake_post(url, payload, headers, timeout):
        model = json.loads(payload)[0]["model"]
        seen_models.append(model)
        if model == llm.DEFAULT_MODEL:
            raise _http_error(502)
        return json.dumps({"data": [{"text": "from fallback", "usage": {}}]}).encode()

    monkeypatch.setattr("agent.services.llm._http.post", fake_post)
    result = llm.complete("a prompt")
    assert result == "from fallback"
    assert seen_models == [llm.DEFAULT_MODEL, llm.FALLBACK_MODEL]


def test_complete_does_not_fall_back_on_a_402(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    seen_models = []

    def fake_post(url, payload, headers, timeout):
        seen_models.append(json.loads(payload)[0]["model"])
        raise _http_error(402)

    monkeypatch.setattr("agent.services.llm._http.post", fake_post)
    with pytest.raises(urllib.error.HTTPError):
        llm.complete("a prompt")
    assert seen_models == [llm.DEFAULT_MODEL]


def test_complete_does_not_fall_back_on_a_400(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr(
        "agent.services.llm._http.post",
        lambda url, payload, headers, timeout: (_ for _ in ()).throw(_http_error(400)),
    )
    with pytest.raises(urllib.error.HTTPError):
        llm.complete("a prompt")


def test_complete_propagates_the_error_when_the_fallback_model_also_fails(monkeypatch):
    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr(
        "agent.services.llm._http.post",
        lambda url, payload, headers, timeout: (_ for _ in ()).throw(_http_error(503)),
    )
    with pytest.raises(urllib.error.HTTPError):
        llm.complete("a prompt")


def test_runware_error_reason_is_kept_in_the_raised_error(monkeypatch):
    # A bare "HTTP Error 400: Bad Request" hid why runs failed on Nov 4.
    import io

    body = json.dumps({"errors": [{"code": "invalidModel", "message": "Model not found"}]}).encode()

    def fake_post(url, payload, headers, timeout):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, io.BytesIO(body))

    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr("agent.services.llm._http.post", fake_post)
    with pytest.raises(urllib.error.HTTPError) as raised:
        llm.complete("a prompt")
    assert str(raised.value) == f"HTTP Error 400: Bad Request ({llm.DEFAULT_MODEL}: invalidModel: Model not found)"
