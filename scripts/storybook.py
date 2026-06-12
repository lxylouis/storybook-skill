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
        # Include the valid commands in each required phase so the error
        # message names the blocked command (e.g. "save-outline").
        allowed_cmds = []
        for a in allowed:
            allowed_cmds.extend(PHASE_NEXT_COMMANDS.get(a, []))
        allowed_cmds_str = ", ".join(allowed_cmds) if allowed_cmds else "(none)"
        _fail(
            "phase=%r, requires %s (available: %s)"
            % (current, ", ".join(allowed), allowed_cmds_str),
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


# ── outline validation (ported from FDA save_outline, tools.py:530-610) ──

def _validate_outline_input(payload):
    """Validate save-outline input; return normalized (meta, pages).

    pages[0] is the cover (page_no=0; page_title exempt); body pages are
    page_no 1..N. ids are CLI-assigned: 'cover', 'page-1', ... Carried
    'image_file' values are preserved (amend-and-resave keeps images).
    """
    if not isinstance(payload, dict):
        _fail("outline file must contain a JSON object")
    title = payload.get("title") or {}
    if not isinstance(title, dict) or not (title.get("zh") or "").strip():
        _fail("title.zh is required")
    if not (title.get("en") or "").strip():
        _fail("title.en is required")
    author = (payload.get("author") or "").strip()
    if not author:
        _fail("author is required")
    sb = (payload.get("style_bible") or "").strip()
    if not sb:
        _fail("style_bible is required",
              hint="Global art-style anchor. See references/prompts.md.")
    cb = (payload.get("character_bible") or "").strip()
    if not cb:
        _fail("character_bible is required",
              hint="One line per character, starting with 'Name:'. "
                   "See references/prompts.md.")
    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        _fail("pages must be a non-empty list")
    if len(pages) < 5:
        _fail("at least 5 pages required, got %d" % len(pages),
              hint="A picture book needs at least 5 pages (cover + 4 body).")
    if len(pages) > 12:
        _fail("at most 12 pages allowed, got %d" % len(pages),
              hint="Keep the story concise; 5-12 pages is the sweet spot.")

    norm = []
    for i, p in enumerate(pages):
        if not isinstance(p, dict):
            _fail("pages[%d] must be an object" % i)
        pno = p.get("page_no", i)
        if pno != i:
            _fail("pages[%d].page_no must be %d (cover=0, body contiguous), got %r"
                  % (i, i, pno))
        if i != 0:
            pt = p.get("page_title")
            if not isinstance(pt, dict):
                _fail("pages[%d].page_title must be a dict with zh/en keys" % i)
            zh = (pt.get("zh") or "").strip()
            en = (pt.get("en") or "").strip()
            if not zh:
                _fail("pages[%d].page_title.zh is required" % i)
            if not en:
                _fail("pages[%d].page_title.en is required" % i)
            if len(zh) < 2 or len(zh) > 15:
                _fail("pages[%d].page_title.zh must be 2-15 chars (got %d)"
                      % (i, len(zh)))
            title_pair = {"zh": zh, "en": en}
        else:
            pt = p.get("page_title") or {}
            title_pair = {"zh": (pt.get("zh") or "").strip(),
                          "en": (pt.get("en") or "").strip()}
        nar = p.get("narration")
        if not isinstance(nar, dict):
            _fail("pages[%d].narration must be a dict with zh/en keys" % i)
        if not (nar.get("zh") or "").strip():
            _fail("pages[%d].narration.zh is required" % i)
        if not (nar.get("en") or "").strip():
            _fail("pages[%d].narration.en is required" % i)
        ipr = (p.get("image_prompt") or "").strip()
        if not ipr:
            _fail("pages[%d].image_prompt is required" % i)
        if len(ipr) > 200:
            _fail("pages[%d].image_prompt too long (%d chars, max 200)"
                  % (i, len(ipr)),
                  hint="只写本页场景/动作/构图，删掉画风词与角色长相——它们由 "
                       "style_bible/character_bible 自动前置。")
        norm.append({
            "id": "cover" if i == 0 else "page-%d" % i,
            "page_no": i,
            "page_title": title_pair,
            "narration": {"zh": nar.get("zh", "").strip(),
                          "en": nar.get("en", "").strip()},
            "image_prompt": ipr,
            "image_file": (p.get("image_file") or "").strip(),
            "failed_attempts": int(p.get("failed_attempts", 0) or 0),
        })
    meta = {
        "title": {"zh": title.get("zh", "").strip(), "en": title.get("en", "").strip()},
        "author": author,
        "story_note": (payload.get("story_note") or "").strip(),
        "style_bible": sb,
        "character_bible": cb,
    }
    return meta, norm


def cmd_save_outline(args):
    data = _load_book(args.dir)
    _require_phase(data, "outlining")
    if args.file == "-":
        raw = sys.stdin.read()
    else:
        f = Path(args.file)
        if not f.is_file():
            _fail("outline file %r not found" % str(f))
        raw = f.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _fail("outline file is not valid JSON: %s" % exc)
    meta, pages = _validate_outline_input(payload)
    data.update(meta)
    data["pages"] = pages
    data["cover"] = {"image_prompt": pages[0]["image_prompt"],
                     "image_file": pages[0]["image_file"]}
    data["current_page_index"] = 0
    data["phase"] = "awaiting_outline_confirm"
    _write_book(args.dir, data)
    _emit({
        "ok": True, "page_count": len(pages),
        "title_zh": meta["title"]["zh"], "title_en": meta["title"]["en"],
        "phase": "awaiting_outline_confirm",
        "next_action": "STOP-AND-CONFIRM flow: 1) generate the COVER image "
                       "now (compose-prompt --page cover → your image tool or "
                       "scripts/gen_image.py → save-image --page cover), "
                       "2) show the user the outline + cover, 3) WAIT for "
                       "explicit user confirmation, then run confirm-outline. "
                       "NEVER confirm in the same breath.",
    })


def _find_page(data, page_id):
    for page in data.get("pages", []):
        if page.get("id") == page_id:
            return page
    _fail("page_id %r not found" % page_id,
          hint="available: %s" % [p.get("id") for p in data.get("pages", [])])


def cmd_save_image(args):
    data = _load_book(args.dir)
    pid = (args.page or "").strip()
    # Cover exception ported from FDA: the outline turn saves the cover
    # right after save-outline advanced phase to awaiting_outline_confirm.
    if pid == "cover":
        _require_phase(data, "illustrating", "delivered", "awaiting_outline_confirm")
    else:
        _require_phase(data, "illustrating", "delivered")
    src = Path(args.file)
    if not src.is_file():
        _fail("image file %r not found" % str(src),
              hint="Generate the image first (host image tool or "
                   "scripts/gen_image.py), then pass its path here.")
    ext = src.suffix.lower()
    if ext not in IMAGE_EXTS:
        _fail("unsupported image extension %r" % ext,
              hint="Use one of: png, jpg, jpeg, webp.")
    page = _find_page(data, pid)
    if pid == "cover":
        dest_name = "cover" + ext
    else:
        dest_name = "page-%02d%s" % (int(page.get("page_no", 0)), ext)
    dest = Path(args.dir) / "images" / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    rel = "images/" + dest_name
    page["image_file"] = rel
    page["failed_attempts"] = 0
    if data["pages"] and data["pages"][0].get("id") == pid:
        data.setdefault("cover", {})["image_file"] = rel
    remaining = sum(1 for p in data["pages"] if not (p.get("image_file") or "").strip())
    _write_book(args.dir, data)
    result = {"ok": True, "page_id": pid, "image_file": rel, "remaining": remaining}
    phase_now = data.get("phase")
    if remaining > 0 and phase_now == "illustrating":
        result["next_action"] = ("%d pages still need images. Report one-line "
                                 "progress to the user, then run `next` to get "
                                 "the next page and keep the auto loop going."
                                 % remaining)
    elif phase_now == "delivered":
        result["next_action"] = "Page image updated. Re-run `export` to refresh the HTML."
    elif phase_now == "awaiting_outline_confirm":
        result["next_action"] = ("Cover saved. Show the user the outline + cover "
                                 "and WAIT for explicit confirmation, then run "
                                 "confirm-outline.")
    else:
        result["next_action"] = "All pages have images. Run `finalize`."
    _emit(result)


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

    p = sub.add_parser("save-image", help="Register a generated image for a page.")
    p.add_argument("--page", required=True, help="cover | page-N")
    p.add_argument("--file", required=True, help="path of the generated image")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_save_image)

    p = sub.add_parser("save-outline", help="Persist the validated outline.")
    p.add_argument("--file", required=True, help="outline JSON path, or - for stdin")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_save_outline)

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
