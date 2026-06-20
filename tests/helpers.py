"""Test helpers: drive scripts/storybook.py as a real subprocess.

Using subprocess (not import) tests the actual CLI contract — argv parsing,
single-line JSON on stdout, exit codes — under whichever interpreter runs
the suite, so the same suite doubles as the 3.9-floor check.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "storybook.py"
GEN_SCRIPT = ROOT / "scripts" / "gen_image.py"
GEN_DS_SCRIPT = ROOT / "scripts" / "gen_image_dashscope.py"

# 1x1 transparent PNG — never decoded by the CLI, only copied/base64'd.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
)


def run_cli(*args, cwd=None, env_extra=None):
    """Run storybook.py with args; return (exit_code, parsed_json, stderr)."""
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True, cwd=str(cwd or ROOT), env=env,
    )
    payload = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return proc.returncode, payload, proc.stderr


def write_book(book_dir, data):
    """Write a book.json fixture directly (tests may fabricate any state)."""
    d = Path(book_dir)
    (d / "images").mkdir(parents=True, exist_ok=True)
    (d / "book.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return d


def read_book(book_dir):
    return json.loads((Path(book_dir) / "book.json").read_text(encoding="utf-8"))


def base_book(phase="outlining", n_body=4, with_images=False):
    """Canonical fixture mirroring scripts/storybook.py's data model.

    pages[0] is the cover (page_no=0, id 'cover'); body pages page-1..N.
    """
    pages = [{
        "id": "cover", "page_no": 0,
        "page_title": {"zh": "", "en": ""},
        "narration": {"zh": "封面", "en": "Cover"},
        "image_prompt": "fox under moon, title mood, weight in upper two thirds",
        "image_file": "images/cover.png" if with_images else "",
        "failed_attempts": 0,
    }]
    for i in range(1, n_body + 1):
        pages.append({
            "id": "page-%d" % i, "page_no": i,
            "page_title": {"zh": "第%d页的标题" % i, "en": "Title %d" % i},
            "narration": {"zh": "嗖——第%d页。" % i, "en": "Whoosh — page %d." % i},
            "image_prompt": "fox walks on path, scene %d" % i,
            "image_file": "images/page-%02d.png" % i if with_images else "",
            "failed_attempts": 0,
        })
    return {
        "version": 1, "phase": phase,
        "idea": "小狐狸找月亮", "audience": "3-6岁", "style": "watercolor", "author": "lxy",
        "style_bible": "Soft watercolor, warm palette.",
        "character_bible": "Little Fox: red fur, amber eyes.\nMoon Granny: silver hair, round glasses, starry shawl.",
        "title": {"zh": "小狐狸找月亮", "en": "Little Fox Seeks the Moon"},
        "story_note": "学会观察与坚持。",
        "cover": {"image_prompt": pages[0]["image_prompt"],
                  "image_file": pages[0]["image_file"]},
        "pages": pages,
        "current_page_index": 0,
        "created_at": "2026-06-12T00:00:00+00:00",
    }


def make_book(tmpdir, **kwargs):
    """Create <tmpdir>/book/ with base_book(**kwargs); also drop image bytes."""
    d = Path(tmpdir) / "book"
    data = base_book(**kwargs)
    write_book(d, data)
    if kwargs.get("with_images"):
        for p in data["pages"]:
            if p["image_file"]:
                (d / p["image_file"]).write_bytes(TINY_PNG)
    return d


def tmp():
    return tempfile.TemporaryDirectory()


# ── fake OpenAI-compatible images API (for test_gen_image.py) ──────────

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeImageAPI:
    """Serves POST /v1/images/generations and GET /img.png on 127.0.0.1.

    mode: "b64" → data[0].b64_json (valid PNG); "url" → data[0].url;
          "apierror" → HTTP 200 carrying {"error":{...}} (gateway-style);
          "empty"    → HTTP 200 with an empty data[];
          "notimage" → HTTP 200 b64 of a non-image body (HTML error page).
    fail_times:   first N POSTs answer 500 (retry testing).
    client_error: if set, the POST answers this 4xx (fast-fail, no retry).
    """

    def __init__(self, mode="b64", fail_times=0, client_error=0):
        self.mode = mode
        self.fail_times = fail_times
        self.client_error = client_error
        self.posts = 0
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                api.posts += 1
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if api.posts <= api.fail_times:
                    self._json(500, {"error": {"message": "boom"}})
                    return
                if api.client_error:
                    self._json(api.client_error, {"error": {"message": "bad request"}})
                    return
                if api.mode == "apierror":
                    self._json(200, {"error": {"message": "content policy"}})
                elif api.mode == "empty":
                    self._json(200, {"data": []})
                elif api.mode == "notimage":
                    self._json(200, {"data": [{"b64_json":
                        base64.b64encode(b"<html>error</html>").decode("ascii")}]})
                elif api.mode == "url":
                    self._json(200, {"data": [{"url":
                        "http://127.0.0.1:%d/img.png" % api.port}]})
                else:  # b64
                    self._json(200, {"data": [{"b64_json":
                        base64.b64encode(TINY_PNG).decode("ascii")}]})

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(TINY_PNG)))
                self.end_headers()
                self.wfile.write(TINY_PNG)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base_url = "http://127.0.0.1:%d/v1" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def run_gen(*args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env.pop("STORYBOOK_IMAGE_API_KEY", None)  # isolate from real env
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(GEN_SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True, cwd=str(cwd or ROOT), env=env,
    )
    payload = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return proc.returncode, payload, proc.stderr


class FakeDashScopeAPI:
    """Minimal DashScope multimodal-generation stub on 127.0.0.1.

    mode: "ok" → returns an image URL pointing back at this server;
          "apierror" → HTTP 200 body carrying code/message (DashScope style);
          "badshape" → HTTP 200 object with no usable output.choices[].image.
    fail_times: first N POSTs answer 500 (retry testing).
    bad_image:  GET /img.png returns a non-image body (expired-link page).
    """

    def __init__(self, mode="ok", fail_times=0, bad_image=False):
        self.mode = mode
        self.fail_times = fail_times
        self.bad_image = bad_image
        self.posts = 0
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, obj):
                body = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                api.posts += 1
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if api.posts <= api.fail_times:
                    self._json(500, {"code": "InternalError", "message": "boom"})
                    return
                if api.mode == "apierror":
                    self._json(200, {"code": "InvalidParameter",
                                     "message": "size not supported",
                                     "request_id": "t"})
                    return
                if api.mode == "badshape":
                    self._json(200, {"output": {"choices": []}, "request_id": "t"})
                    return
                self._json(200, {
                    "output": {"choices": [{"message": {"content": [
                        {"image": "http://127.0.0.1:%d/img.png" % api.port}]}}]},
                    "usage": {}, "request_id": "t",
                })

            def do_GET(self):
                body = b"<html>error</html>" if api.bad_image else TINY_PNG
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base_url = "http://127.0.0.1:%d/api/v1" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def run_gen_ds(*args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env.pop("STORYBOOK_IMAGE_API_KEY", None)  # isolate from real env
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(GEN_DS_SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True, cwd=str(cwd or ROOT), env=env,
    )
    payload = {}
    if proc.stdout.strip():
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    return proc.returncode, payload, proc.stderr
