#!/usr/bin/env python3
"""DashScope (阿里云百炼) image generator — wan2.7-image / wan2.7-image-pro.

Used when the host agent has no image-generation tool of its own.
Reads the prompt, POSTs to DashScope multimodal-generation endpoint,
downloads the returned image URL, writes the image to --out, and prints
a single JSON line. Exit codes: 0 ok / 2 config-or-provider error / 1 unexpected.

Env:
  STORYBOOK_IMAGE_API_KEY    (required) — your DashScope API key
  STORYBOOK_IMAGE_BASE_URL   default https://dashscope.aliyuncs.com/api/v1
  STORYBOOK_IMAGE_MODEL      default wan2.7-image
  STORYBOOK_IMAGE_SIZE       default 1024x1536 (portrait ~2:3)
                             DashScope format: "WxH" or "W×H", both in [768,2048]

Python 3.9 compatible, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path


def _emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def _fail(error, hint=""):
    payload = {"error": error}
    if hint:
        payload["hint"] = hint
    _emit(payload, 2)


def _read_prompt(args):
    if args.prompt:
        return args.prompt.strip()
    if args.prompt_file:
        if args.prompt_file == "-":
            return sys.stdin.read().strip()
        p = Path(args.prompt_file)
        if not p.is_file():
            _fail("prompt file %r not found" % str(p))
        return p.read_text(encoding="utf-8").strip()
    _fail("no prompt given", hint="Pass --prompt '...' or --prompt-file <path|->.")


def _post_json(url, payload, api_key, timeout=300):
    """POST JSON to DashScope API, return parsed response."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer %s" % api_key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_size(size_str):
    """Convert skill-style size to DashScope format.

    The skill uses OpenAI style like "1024x1536". DashScope expects
    "1024×1536" (multiplication sign) or "2K" / "1K". We convert
    "WxH" → "W×H" and validate constraints.
    """
    s = size_str.strip()
    # Already a preset keyword
    if s.upper() in ("1K", "2K"):
        return s.upper()
    # Convert "WxH" or "W*H" to "W×H"
    import re
    m = re.match(r"^(\d{3,4})\s*[x×\*X]\s*(\d{3,4})$", s)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w < 768 or w > 2048 or h < 768 or h > 2048:
            _fail(
                "size %s out of range" % s,
                hint="Width and height must each be in [768, 2048] for DashScope. "
                     "Try 1024×1536 for portrait, or use '2K' for 2048×2048.",
            )
        ratio = max(w, h) / min(w, h)
        if ratio > 8:
            _fail(
                "aspect ratio %.2f:1 exceeds DashScope limit (8:1)" % ratio,
                hint="Use a less extreme aspect ratio.",
            )
        return "%d×%d" % (w, h)
    # Fall through: pass as-is (let the API reject it)
    return s


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gen_image_dashscope.py")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--size", default="")
    args = parser.parse_args(argv)

    try:
        api_key = os.environ.get("STORYBOOK_IMAGE_API_KEY", "").strip()
        if not api_key:
            _fail(
                "STORYBOOK_IMAGE_API_KEY is not set",
                hint="export STORYBOOK_IMAGE_API_KEY=<your-dashscope-api-key> — "
                     "or use the host agent's own image tool instead of this "
                     "fallback. Optional: STORYBOOK_IMAGE_BASE_URL / _MODEL / _SIZE.",
            )

        base_url = os.environ.get(
            "STORYBOOK_IMAGE_BASE_URL",
            "https://dashscope.aliyuncs.com/api/v1",
        ).rstrip("/")

        model = os.environ.get("STORYBOOK_IMAGE_MODEL", "wan2.7-image").strip()
        raw_size = (
            args.size
            or os.environ.get("STORYBOOK_IMAGE_SIZE", "1024x1536")
        ).strip()
        size = _normalize_size(raw_size)

        retry_sleep = float(
            os.environ.get("STORYBOOK_IMAGE_RETRY_BASE_SLEEP", "2")
        )
        prompt = _read_prompt(args)

        # Build DashScope request body
        payload = {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ]
            },
            "parameters": {
                "size": size,
                "n": 1,
            },
        }

        # DashScope endpoint (not OpenAI compatible)
        url = base_url + "/services/aigc/multimodal-generation/generation"

        last_err = None
        result = None
        for attempt in range(3):  # 1 try + 2 retries on 5xx/network
            try:
                result = _post_json(url, payload, api_key)
                break
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:500]
                except Exception:
                    pass
                if exc.code >= 500:
                    last_err = "HTTP %d from provider: %s" % (exc.code, body)
                else:
                    _fail(
                        "provider rejected the request (HTTP %d): %s"
                        % (exc.code, body),
                        hint="Check model/size against the DashScope docs. "
                             "Size in use: %r. Model: %r. "
                             "See https://help.aliyun.com/model-studio/error-code"
                             % (size, model),
                    )
            except urllib.error.URLError as exc:
                last_err = "network error: %s" % exc
            if attempt < 2:
                time.sleep(retry_sleep * (attempt + 1))

        if result is None:
            _fail(
                "image generation failed after 3 attempts: %s" % last_err,
                hint="Transient provider/network failure. Re-run this command; "
                     "if it persists, run `storybook.py regenerate` to log the "
                     "attempt and consider `skip` after 3 failures.",
            )

        # Check for API-level error
        if "code" in result and "message" in result:
            _fail(
                "DashScope returned error: %s — %s"
                % (result.get("code"), result.get("message")),
                hint="See https://help.aliyun.com/model-studio/error-code for "
                     "error code reference.",
            )

        # Extract image URL from response
        try:
            image_url = (
                result["output"]["choices"][0]["message"]["content"][0]["image"]
            )
        except (KeyError, IndexError, TypeError):
            _fail(
                "unexpected DashScope response structure",
                hint="Raw response keys: %s" % list(result.keys())
                     if isinstance(result, dict) else str(result)[:300],
            )

        # Download the image (URL valid for 24h per DashScope docs)
        for attempt in range(3):
            try:
                with urllib.request.urlopen(image_url, timeout=180) as resp:
                    img_bytes = resp.read()
                break
            except urllib.error.URLError as exc:
                last_err = "image download error: %s" % exc
                if attempt < 2:
                    time.sleep(retry_sleep * (attempt + 1))
        else:
            _fail(
                "failed to download image from URL after 3 attempts: %s" % last_err,
                hint="The URL may have expired (DashScope URLs last 24h). "
                     "Re-generate the image.",
            )

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)

        _emit({
            "ok": True,
            "out": str(out_path.resolve()),
            "size_bytes": len(img_bytes),
            "model": model,
            "size": size,
        })

    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc()
        _emit({"error": "unexpected: %s" % exc}, 1)


if __name__ == "__main__":
    main()
