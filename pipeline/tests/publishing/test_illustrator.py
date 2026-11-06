import io

from PIL import Image

from agent.publishing import illustrator

# `illustrate()`/`_default_client()` treat whatever a client returns as
# opaque, already-compressed WebP bytes - a client fake at this boundary
# only needs to look like a valid WebP container, not actually decode.
_VALID_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 1000
_TOO_SMALL_WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 10
_BAD_MAGIC = b"not a webp at all" + b"0" * 1000


def _real_png_bytes() -> bytes:
    """A genuinely decodable PNG, for tests that exercise a real provider
    client (`_runware_client`/`_openai_client`) directly - those clients
    now call Pillow's `Image.open` on the "provider response", so a fake
    that's just magic bytes isn't enough here."""
    image = Image.new("RGB", (4, 4), color=(200, 50, 50))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_illustrate_returns_valid_webp_bytes():
    data = illustrator.illustrate("a prompt", client=lambda p: _VALID_WEBP)
    assert data == _VALID_WEBP


def test_illustrate_rejects_a_response_with_bad_magic_bytes():
    import pytest

    with pytest.raises(ValueError):
        illustrator.illustrate("a prompt", client=lambda p: _BAD_MAGIC)


def test_illustrate_rejects_a_response_below_the_minimum_size():
    import pytest

    with pytest.raises(ValueError):
        illustrator.illustrate("a prompt", client=lambda p: _TOO_SMALL_WEBP)


def test_illustrate_caches_by_prompt_fingerprint(tmp_path):
    calls = []

    def client(prompt: str) -> bytes:
        calls.append(prompt)
        return _VALID_WEBP

    illustrator.illustrate("same prompt", client=client, cache_dir=tmp_path)
    illustrator.illustrate("same prompt", client=client, cache_dir=tmp_path)
    assert len(calls) == 1


def test_generate_images_enabled_defaults_to_false(monkeypatch):
    monkeypatch.delenv("WEARY_GENERATE_IMAGES", raising=False)
    assert illustrator.generate_images_enabled() is False


def test_generate_images_enabled_reads_env_var(monkeypatch):
    monkeypatch.setenv("WEARY_GENERATE_IMAGES", "true")
    assert illustrator.generate_images_enabled() is True


def test_default_client_uses_placeholder_when_images_disabled(monkeypatch):
    monkeypatch.delenv("WEARY_GENERATE_IMAGES", raising=False)
    monkeypatch.setattr(illustrator, "_placeholder_client", lambda p: _VALID_WEBP)

    def fail_if_called(p):
        raise AssertionError("OpenAI client should not be called when images are disabled")

    monkeypatch.setattr(illustrator, "_openai_client", fail_if_called)
    assert illustrator._default_client("a prompt") == _VALID_WEBP


def test_default_client_uses_runware_by_default_when_images_enabled(monkeypatch):
    monkeypatch.setenv("WEARY_GENERATE_IMAGES", "true")
    monkeypatch.delenv("WEARY_IMAGE_PROVIDER", raising=False)
    monkeypatch.setattr(illustrator, "_runware_client", lambda p: _VALID_WEBP)

    def fail_if_called(p):
        raise AssertionError("openai/placeholder client should not be called")

    monkeypatch.setattr(illustrator, "_openai_client", fail_if_called)
    monkeypatch.setattr(illustrator, "_placeholder_client", fail_if_called)
    assert illustrator._default_client("a prompt") == _VALID_WEBP


def test_default_client_uses_openai_when_provider_is_set(monkeypatch):
    monkeypatch.setenv("WEARY_GENERATE_IMAGES", "true")
    monkeypatch.setenv("WEARY_IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(illustrator, "_openai_client", lambda p: _VALID_WEBP)

    def fail_if_called(p):
        raise AssertionError("runware/placeholder client should not be called")

    monkeypatch.setattr(illustrator, "_runware_client", fail_if_called)
    monkeypatch.setattr(illustrator, "_placeholder_client", fail_if_called)
    assert illustrator._default_client("a prompt") == _VALID_WEBP


def test_default_client_rejects_an_unknown_provider(monkeypatch):
    import pytest

    monkeypatch.setenv("WEARY_GENERATE_IMAGES", "true")
    monkeypatch.setenv("WEARY_IMAGE_PROVIDER", "midjourney")
    with pytest.raises(ValueError):
        illustrator._default_client("a prompt")


def test_runware_client_returns_a_compressed_webp(monkeypatch):
    import base64
    import json

    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    encoded = base64.b64encode(_real_png_bytes()).decode()

    def fake_post(url, payload, headers, timeout):
        assert url == "https://api.runware.ai/v1"
        assert headers["Authorization"] == "Bearer test-key"
        [task] = json.loads(payload)
        assert task["taskType"] == "imageInference"
        assert task["outputType"] == "base64Data"
        assert task["outputFormat"] == "PNG"
        return json.dumps({"data": [{"imageBase64Data": encoded}]}).encode()

    monkeypatch.setattr(illustrator._http, "post", fake_post)
    result = illustrator._runware_client("a prompt")
    assert result[:4] == b"RIFF" and result[8:12] == b"WEBP"


def test_runware_client_raises_on_an_error_response(monkeypatch):
    import json

    import pytest

    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")

    def fake_post(url, payload, headers, timeout):
        return json.dumps({"errors": [{"code": "invalidApiKey", "message": "bad key"}]}).encode()

    monkeypatch.setattr(illustrator._http, "post", fake_post)
    with pytest.raises(ValueError):
        illustrator._runware_client("a prompt")


def test_compress_to_webp_produces_a_valid_smaller_webp():
    png_bytes = _real_png_bytes()
    webp_bytes = illustrator._compress_to_webp(png_bytes)
    assert webp_bytes[:4] == b"RIFF" and webp_bytes[8:12] == b"WEBP"


def _webp(color, noisy=False) -> bytes:
    image = Image.new("RGB", (64, 48), color=color)
    if noisy:
        for x in range(0, 64, 2):
            for y in range(48):
                image.putpixel((x, y), (255, 255, 255))
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=90)
    data = buf.getvalue()
    return data + b"\x00" * max(0, 1001 - len(data))  # stay above the minimum size check


def test_a_blank_image_is_regenerated(monkeypatch):
    # Nov 3: Runware returned a solid black cover and it was published.
    replies = iter([_webp((0, 0, 0)), _webp((10, 80, 160), noisy=True)])
    calls = []
    data = illustrator.illustrate("a prompt", client=lambda p: calls.append(p) or next(replies))
    assert len(calls) == 2 and not illustrator._is_blank(data)


def test_an_image_still_blank_after_retries_falls_back_to_the_placeholder(monkeypatch, tmp_path):
    placeholder = _webp((200, 200, 200), noisy=True)
    monkeypatch.setattr(illustrator, "_placeholder_client", lambda prompt: placeholder)
    calls = []
    data = illustrator.illustrate("a prompt", client=lambda p: calls.append(p) or _webp((0, 0, 0)), cache_dir=tmp_path)
    assert data == placeholder
    assert len(calls) == 1 + illustrator._MAX_BLANK_RETRIES
    assert not list(tmp_path.iterdir())  # the fallback is not cached


def test_runware_requests_the_nsfw_flag(monkeypatch):
    import base64
    import json

    seen = {}

    def fake_post(url, payload, headers, timeout):
        seen.update(json.loads(payload)[0])
        return json.dumps({"data": [{"imageBase64Data": base64.b64encode(_real_png_bytes()).decode()}]}).encode()

    monkeypatch.setenv("RUNWARE_API_KEY", "test-key")
    monkeypatch.setattr("agent.publishing.illustrator._http.post", fake_post)
    illustrator._runware_client("a prompt")
    assert seen["checkNSFW"] is True
