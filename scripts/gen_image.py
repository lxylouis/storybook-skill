#!/usr/bin/env python3
"""Fallback image generator — OpenAI-compatible /images/generations dialect.

Used when the host agent has no image-generation tool of its own. Reads the
prompt, POSTs to ${STORYBOOK_IMAGE_BASE_URL}/images/generations, accepts both
b64_json and url response shapes, writes the image to --out, prints a single
JSON line. Exit codes: 0 ok / 2 config-or-provider error / 1 unexpected.

Env:
  STORYBOOK_IMAGE_API_KEY    (required)
  STORYBOOK_IMAGE_BASE_URL   default https://api.openai.com/v1
  STORYBOOK_IMAGE_MODEL      default gpt-image-1
  STORYBOOK_IMAGE_SIZE       default 1024x1536 (portrait; provider-specific —
                             see README provider table)

Python 3.9 compatible, stdlib only.
"""
from __future__ import annotations

import argparse
import base64
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


def _post_json(url, payload, api_key, timeout=180):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer %s" % api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gen_image.py")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prompt-file", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--size", default="")
    args = parser.parse_args(argv)

    try:
        api_key = os.environ.get("STORYBOOK_IMAGE_API_KEY", "").strip()
        if not api_key:
            _fail("STORYBOOK_IMAGE_API_KEY is not set",
                  hint="export STORYBOOK_IMAGE_API_KEY=<key> — or use the host "
                       "agent's own image tool instead of this fallback. "
                       "Optional: STORYBOOK_IMAGE_BASE_URL / _MODEL / _SIZE.")
        base_url = os.environ.get(
            "STORYBOOK_IMAGE_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        model = os.environ.get("STORYBOOK_IMAGE_MODEL", "gpt-image-1")
        size = (args.size or os.environ.get("STORYBOOK_IMAGE_SIZE", "1024x1536")).strip()
        retry_sleep = float(os.environ.get("STORYBOOK_IMAGE_RETRY_BASE_SLEEP", "2"))
        prompt = _read_prompt(args)

        payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
        url = base_url + "/images/generations"
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
                    _fail("provider rejected the request (HTTP %d): %s"
                          % (exc.code, body),
                          hint="Check model/size against the provider's docs "
                               "(see README provider table) and the prompt for "
                               "policy issues. Size in use: %r." % size)
            except urllib.error.URLError as exc:
                last_err = "network error: %s" % exc
            if attempt < 2:
                time.sleep(retry_sleep * (attempt + 1))
        if result is None:
            _fail("image generation failed after 3 attempts: %s" % last_err,
                  hint="Transient provider/network failure. Re-run this "
                       "command; if it persists, run `storybook.py regenerate` "
                       "to log the attempt and consider `skip` after 3 failures.")

        data = (result.get("data") or [{}])[0]
        img_bytes = None
        if data.get("b64_json"):
            img_bytes = base64.b64decode(data["b64_json"])
        elif data.get("url"):
            with urllib.request.urlopen(data["url"], timeout=180) as resp:
                img_bytes = resp.read()
        if not img_bytes:
            _fail("provider returned neither b64_json nor url",
                  hint="Raw response keys: %s" % list(result.keys()))

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(img_bytes)
        _emit({"ok": True, "out": str(out_path.resolve()),
               "size_bytes": len(img_bytes), "model": model, "size": size})
    except SystemExit:
        raise
    except Exception as exc:
        traceback.print_exc()
        _emit({"error": "unexpected: %s" % exc}, 1)


if __name__ == "__main__":
    main()
