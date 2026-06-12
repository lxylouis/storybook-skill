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
