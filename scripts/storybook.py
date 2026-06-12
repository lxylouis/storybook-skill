#!/usr/bin/env python3
"""storybook skill CLI — single-book picture-book state machine.

One directory = one book: book.json (single source of truth) + images/ +
exported <slug>.html. This CLI is the ONLY writer of book.json; agents must
never hand-edit it. Guard errors return {"error","hint","current_phase"} on
stdout with exit code 2 so the calling agent can self-correct (same
error-as-hint protocol as the FDA storybook activity this skill is forked
from).

Python 3.9 compatible, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

PHASES = ["outlining", "awaiting_outline_confirm", "illustrating", "delivered"]
SKIP_SENTINEL = "skipped"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# Commands that move the flow forward from each phase (code truth for guard
# hints — ported from FDA tools.py _PHASE_NEXT_TOOLS).
PHASE_NEXT_COMMANDS = {
    "outlining": ["save-outline"],
    "awaiting_outline_confirm": [
        "save-image --page cover", "confirm-outline", "amend-outline",
    ],
    "illustrating": [
        "compose-prompt", "save-image", "next", "skip", "finalize",
    ],
    "delivered": ["amend-page", "regenerate", "export"],
}


# ── output helpers ──────────────────────────────────────────────────────

def _emit(payload, code=0):
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def _fail(error, hint="", current_phase=None):
    payload = {"error": error}
    if hint:
        payload["hint"] = hint
    if current_phase is not None:
        payload["current_phase"] = current_phase
    _emit(payload, 2)


# ── book.json IO ────────────────────────────────────────────────────────

def _book_path(book_dir):
    return Path(book_dir) / "book.json"


def _load_book(book_dir):
    p = _book_path(book_dir)
    if not p.is_file():
        _fail(
            "book.json not found in %r" % str(book_dir),
            hint="Not a book directory. Run `init --idea ...` to start a new "
                 "book, or pass --dir pointing at an existing one.",
        )
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(
            "book.json is corrupted: %s" % exc,
            hint="Restore from book.json.bak (copy it over book.json) and "
                 "re-run `status`.",
        )
    return data


def _write_book(book_dir, data):
    """Atomic write with one-generation backup (accident firewall)."""
    p = _book_path(book_dir)
    if p.is_file():
        shutil.copyfile(p, p.with_suffix(".json.bak"))
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)


# ── guard (ported from FDA tools.py _check_phase) ───────────────────────

def _require_phase(data, *allowed):
    current = data.get("phase", "")
    if current not in allowed:
        nxt = ", ".join(PHASE_NEXT_COMMANDS.get(current, [])) or "(none)"
        _fail(
            "phase=%r, requires %s" % (current, ", ".join(allowed)),
            hint="current phase = '%s'; this command requires phase in: %s. "
                 "Commands that move forward from '%s': %s." % (
                     current, ", ".join(allowed), current, nxt),
            current_phase=current,
        )


# ── commands ────────────────────────────────────────────────────────────

def _default_book(idea, audience, style, author):
    return {
        "version": 1,
        "phase": "outlining",
        "idea": idea, "audience": audience, "style": style, "author": author,
        "style_bible": "", "character_bible": "",
        "title": {"zh": "", "en": ""},
        "story_note": "",
        "cover": {"image_prompt": "", "image_file": ""},
        "pages": [],
        "current_page_index": 0,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def cmd_init(args):
    idea = (args.idea or "").strip()
    if not idea:
        _fail("idea is required", hint="Pass --idea '<one-line story idea>'.")
    slug = (args.slug or "").strip()
    if slug:
        if not re.match(r"^[a-zA-Z0-9_-]+$", slug):
            _fail("slug must match ^[a-zA-Z0-9_-]+$ (got %r)" % slug,
                  hint="Use ASCII letters/digits/hyphen, e.g. --slug little-fox.")
    else:
        # Ported from FDA save_intake slug derivation (tools.py:422-424).
        slug = re.sub(r"[^a-z0-9-]+", "-", idea.lower()).strip("-")[:40]
        if not slug:
            slug = "book"  # pure CJK / symbol ideas fall back
    parent = Path(args.dir)
    book_dir = parent / slug
    if _book_path(book_dir).is_file():
        _fail("book directory %r already exists" % str(book_dir),
              hint="Pick another --slug, or cd into it and run `status` to resume.")
    (book_dir / "images").mkdir(parents=True, exist_ok=True)
    _write_book(book_dir, _default_book(
        idea, (args.audience or "").strip(), (args.style or "").strip(),
        (args.author or "").strip()))
    _emit({
        "ok": True, "slug": slug, "book_dir": str(book_dir.resolve()),
        "phase": "outlining",
        "next_action": "Design the story outline (5-12 pages INCLUDING the "
                       "cover as pages[0], page_no=0). Write style_bible + "
                       "character_bible, then run: save-outline --file "
                       "outline.json --dir <book_dir>. See references/prompts.md.",
    })


def cmd_status(args):
    book_dir = Path(args.dir)
    if not _book_path(book_dir).is_file():
        _emit({
            "ok": True, "exists": False, "phase": None,
            "next_action": "No book here. Run: init --idea '<one-line idea>' "
                           "[--slug my-book] [--audience ...] [--style ...] "
                           "[--author ...] --dir <parent-dir>",
        })
    data = _load_book(book_dir)
    _emit({"ok": True, "exists": True, "phase": data.get("phase", "")})


# ── parser / main ───────────────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        prog="storybook.py",
        description="Single-book picture-book state machine (Agent Skills CLI).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Create a new book directory.")
    p.add_argument("--idea", required=True)
    p.add_argument("--slug", default="")
    p.add_argument("--audience", default="")
    p.add_argument("--style", default="")
    p.add_argument("--author", default="")
    p.add_argument("--dir", default=".", help="PARENT directory (init only).")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("status", help="Phase, progress, and next action.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_status)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # unexpected crash → exit 1, traceback to stderr
        traceback.print_exc()
        _emit({"error": "unexpected: %s" % exc}, 1)


if __name__ == "__main__":
    main()
