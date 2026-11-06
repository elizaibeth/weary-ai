"""Shared text-generation client for research/writer/repairer (not Jev -
TypeSafe's own client lives in verifier.py).

Calls Runware's hosted text models, which also return a real dollar cost
per call. The default was DeepSeek V4 Flash until Runware's backend for it
was shut down on 30 October 2026 (every call then returned HTTP 400);
GPT-5.4 mini replaced it after a smoke test of the models Runware accepts.
Each role can still be overridden with WEARY_RESEARCH_MODEL,
WEARY_WRITER_MODEL and WEARY_REPAIRER_MODEL.

If the primary model's backend is itself down (a real, observed failure
mode: Runware returned a sustained `providerUnavailable` 502 for its
DeepSeek V4 Flash backend), `_http.post` already retries the same model
several times before giving up - once that's exhausted, `complete()`
retries once more against a single fallback model on a different
provider, but only for retryable/server-side statuses. A 4xx (bad
request, or 402 for an exhausted account balance) is never retried with a
different model: that failure is about the request or the account, not
the specific backend, so silently retrying elsewhere would just mask it.
"""

import json
import os
import urllib.error
import uuid

from agent.services import _http, costs

_ENDPOINT = "https://api.runware.ai/v1"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# The fallback is on a different provider so one backend outage cannot stop both.
DEFAULT_MODEL = "openai:gpt@5.4-mini"
FALLBACK_MODEL = "google:gemini@3.1-flash-lite"


def complete(prompt: str, model: str = DEFAULT_MODEL) -> str:
    fallback_model = os.environ.get("WEARY_LLM_FALLBACK_MODEL") or FALLBACK_MODEL
    try:
        return _complete_once(prompt, model)
    except urllib.error.HTTPError as e:
        if e.code not in _RETRYABLE_STATUS or model == fallback_model:
            raise
        return _complete_once(prompt, fallback_model)


def _complete_once(prompt: str, model: str) -> str:
    api_key = os.environ["RUNWARE_API_KEY"]
    # No outputFormat/jsonSchema here: Runware requires a jsonSchema
    # whenever outputFormat is "JSON", which we don't have one-size-fits-
    # all for - every caller's prompt already instructs "return strict
    # JSON" and just `json.loads()`s the free-text response, the same way
    # they did before Runware hosted the text models.
    payload = json.dumps(
        [
            {
                "taskType": "textInference",
                "taskUUID": str(uuid.uuid4()),
                "model": model,
                "includeCost": True,
                "includeUsage": True,
                "messages": [{"role": "user", "content": prompt}],
            }
        ]
    ).encode()
    try:
        raw = _http.post(
            _ENDPOINT,
            payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
    except urllib.error.HTTPError as error:
        # Runware explains rejections in the body (e.g. disabledApiKey, an
        # unknown model). Keep that reason in the exception text so it
        # reaches the run log and the Slack alert instead of a bare status.
        detail = _error_detail(error)
        if detail:
            error.msg = f"{error.msg} ({model}: {detail})"
        raise
    body = json.loads(raw)
    result = body["data"][0]
    usage = result.get("usage") or {}
    costs.record_text_usage(
        {
            "prompt_tokens": usage.get("promptTokens", 0),
            "completion_tokens": usage.get("completionTokens", 0),
        }
    )
    costs.record_text_cost(result.get("cost"))
    return result["text"]


def _error_detail(error: urllib.error.HTTPError) -> str:
    try:
        errors = json.loads(error.read()).get("errors") or []
        return "; ".join(f"{e.get('code', '?')}: {e.get('message', '')}".strip() for e in errors)[:500]
    except Exception:
        return ""
