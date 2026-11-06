"""Render the article's cover illustration from an image prompt.

Real image generation is gated behind `WEARY_GENERATE_IMAGES` (default off,
since it's real per-call spend). While off, a free placeholder image
(placehold.co) is used instead, so the pipeline still produces a valid,
correctly-sized cover image without any image-generation cost. When on,
`WEARY_IMAGE_PROVIDER` picks the real provider: "runware" (default, cheap)
or "openai". Every provider returns essentially uncompressed PNG bytes (a
1536x1024 image at ~4.7MB, roughly the raw uncompressed pixel size) - each
client re-encodes its own response as WebP before returning, cutting that
by 80-99%+ with no visible quality loss for this house style's flat,
solid-colour illustrations. The response is validated as a well-formed
WebP and cached on disk keyed by a fingerprint of the prompt, so retries
with an unchanged prompt (e.g. across a repair loop) don't re-fetch it.
"""

import base64
import hashlib
import io
import json
import logging
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageStat

from agent.services import _http, costs

log = logging.getLogger(__name__)

_MIN_IMAGE_BYTES = 1000
_WEBP_QUALITY = 85
_PLACEHOLDER_URL = "https://placehold.co/1536x1024.png"
# A provider occasionally returns a solid black image (seen 2026-11-03 for a
# school-themed prompt). New calls use new seeds, so regenerate a few times.
_MAX_BLANK_RETRIES = 2
_BLANK_STDDEV = 2.0  # per-channel pixel standard deviation; black is 0

Client = Callable[[str], bytes]


def _fingerprint(image_prompt: str) -> str:
    return hashlib.sha256(image_prompt.encode()).hexdigest()


def _compress_to_webp(image_bytes: bytes, quality: int = _WEBP_QUALITY) -> bytes:
    """Re-encodes whatever the provider returned (essentially uncompressed
    PNG) as a properly compressed WebP - a lossless format round-trip
    would still leave these images an order of magnitude larger than
    necessary, since the source was never really "compressed" to begin
    with."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def _validate(data: bytes) -> None:
    if not (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or len(data) < _MIN_IMAGE_BYTES:
        raise ValueError("Image data is not a valid, properly sized WebP")


def _is_blank(data: bytes) -> bool:
    """True when the image is one flat colour. Undecodable data is left to _validate."""
    try:
        image = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        return False
    return all(deviation < _BLANK_STDDEV for deviation in ImageStat.Stat(image).stddev)


def generate_images_enabled() -> bool:
    return os.environ.get("WEARY_GENERATE_IMAGES", "false").strip().lower() == "true"


def _runware_client(image_prompt: str) -> bytes:
    api_key = os.environ["RUNWARE_API_KEY"]
    payload = json.dumps(
        [
            {
                "taskType": "imageInference",
                "taskUUID": str(uuid.uuid4()),
                "model": os.environ.get("WEARY_IMAGE_MODEL", "runware:100@1"),
                "positivePrompt": image_prompt,
                "width": 1536,
                "height": 1024,
                "outputType": "base64Data",
                "outputFormat": "PNG",
                "checkNSFW": True,  # reports whether a safety filter altered the image
            }
        ]
    ).encode()
    body = json.loads(
        _http.post(
            "https://api.runware.ai/v1",
            payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
    )
    if "errors" in body:
        raise ValueError(f"Runware API error: {body['errors']}")
    result = body["data"][0]
    costs.record_image_cost(result.get("cost"))
    if result.get("NSFWContent"):
        log.info("Runware flagged this image as NSFW content (it may be blanked)")
    return _compress_to_webp(base64.b64decode(result["imageBase64Data"], validate=True))


def _openai_client(image_prompt: str) -> bytes:
    api_key = os.environ["OPENAI_API_KEY"]
    payload = json.dumps(
        {
            "model": os.environ.get("WEARY_IMAGE_MODEL", "gpt-image-2.5-flare"),
            "prompt": image_prompt,
            "n": 1,
            "size": "1536x1024",
            "quality": "medium",
            "output_format": "png",
        }
    ).encode()
    body = json.loads(
        _http.post(
            "https://api.openai.com/v1/images/generations",
            payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
    )
    costs.record_image_cost(None)  # OpenAI's image endpoint reports no cost/usage
    return _compress_to_webp(base64.b64decode(body["data"][0]["b64_json"], validate=True))


def _placeholder_client(image_prompt: str) -> bytes:
    return _compress_to_webp(_http.get(_PLACEHOLDER_URL, timeout=20))


def _default_client(image_prompt: str) -> bytes:
    if not generate_images_enabled():
        return _placeholder_client(image_prompt)
    provider = os.environ.get("WEARY_IMAGE_PROVIDER", "runware").strip().lower()
    if provider == "openai":
        return _openai_client(image_prompt)
    if provider == "runware":
        return _runware_client(image_prompt)
    raise ValueError(f"Unknown WEARY_IMAGE_PROVIDER: {provider!r}")


def illustrate(image_prompt: str, client: Client = _default_client, cache_dir: Path | None = None) -> bytes:
    cache_path = cache_dir / f"{_fingerprint(image_prompt)}.webp" if cache_dir else None
    if cache_path and cache_path.exists():
        log.info("image cache hit (%s)", cache_path.name)
        return cache_path.read_bytes()

    mode = "real" if generate_images_enabled() else "placeholder"
    provider = os.environ.get("WEARY_IMAGE_PROVIDER", "runware").strip().lower() if mode == "real" else "placehold.co"
    log.info("generating image via %s (%s)...", provider, mode)
    data = client(image_prompt)
    _validate(data)
    for attempt in range(1, _MAX_BLANK_RETRIES + 1):
        if not _is_blank(data):
            break
        log.info("image is blank (one flat colour); regenerating (%s/%s)...", attempt, _MAX_BLANK_RETRIES)
        data = client(image_prompt)
        _validate(data)
    if _is_blank(data):
        # Never publish a blank cover; the placeholder at least shows it is missing.
        log.info("WARNING: image still blank after retries; using the placeholder image")
        data = _placeholder_client(image_prompt)
        _validate(data)
        return data  # not cached, so a later run tries the provider again
    log.info("image: %s bytes", len(data))

    if cache_dir and cache_path:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(data)
    return data
