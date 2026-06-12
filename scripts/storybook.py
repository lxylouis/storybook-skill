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


# Canonical consistency constraint string — ported verbatim from FDA
# tools.py:251-254. Kept short to leave room for style_bible +
# character_bible + image_prompt within the 500-char budget.
CONSISTENCY_CONSTRAINTS = (
    "Same character design and art style across all pages; "
    "coherent lighting and palette; centered subject; no text or captions."
)


def cmd_compose_prompt(args):
    data = _load_book(args.dir)
    pid = (args.page or "").strip()
    if pid == "cover":
        _require_phase(data, "illustrating", "delivered", "awaiting_outline_confirm")
    else:
        _require_phase(data, "illustrating", "delivered")
    style = (data.get("style_bible") or "").strip()
    full_character = (data.get("character_bible") or "").strip()

    # characters 是角色名过滤器:从 character_bible 里挑出对应角色的完整设定
    # 条目。名字匹配不到(或没传)一律回退全量 bible——角色锚永远在场,防止
    # "只传名字导致角色设定丢失→跨页漂移"。(移植 tools.py:298-311)
    chars = full_character
    requested = (args.characters or "").strip()
    if requested and full_character:
        entries = [e.strip() for e in re.split(r"[\n;；]+", full_character) if e.strip()]
        names = [n.strip() for n in re.split(r"[,，、/|\s]+", requested) if n.strip()]
        matched = [e for e in entries
                   if any(n.lower() in e.lower() for n in names)]
        if matched:
            chars = "; ".join(matched)

    page = _find_page(data, pid)
    ipr = (page.get("image_prompt") or "").strip()
    if not ipr:
        _fail("image_prompt not found for page %r" % pid,
              hint="available: %s" % [p.get("id") for p in data.get("pages", [])])

    # Truncate each section to fit 500 chars (FDA budgets: 100/120/180).
    style = style[:100].strip()
    chars = chars[:120].strip()
    ipr = ipr[:180].strip()
    parts = [s for s in [style, chars, ipr, CONSISTENCY_CONSTRAINTS] if s]
    prompt = "\n".join(parts)
    if len(prompt) > 500:
        prompt = prompt[:497].strip() + "..."
    _emit({
        "ok": True, "page_id": pid, "prompt": prompt, "prompt_len": len(prompt),
        "next_action": "Generate ONE portrait (~2:3) image from this prompt — "
                       "use the host's image tool if available, else "
                       "scripts/gen_image.py. Do NOT modify the prompt. Then "
                       "run save-image --page %s --file <generated>." % pid,
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


def _page_brief(page):
    return {
        "page_id": page.get("id", ""), "page_no": page.get("page_no", 0),
        "page_title": page.get("page_title", {}),
        "narration": page.get("narration", {}),
        "image_prompt": page.get("image_prompt", ""),
    }


def cmd_confirm_outline(args):
    data = _load_book(args.dir)
    _require_phase(data, "awaiting_outline_confirm")
    cover_file = (data.get("cover", {}).get("image_file") or "").strip()
    if not cover_file or cover_file == SKIP_SENTINEL:
        _fail("cover image missing — cannot confirm outline",
              hint="Generate the cover first: compose-prompt --page cover → "
                   "image tool / scripts/gen_image.py → save-image --page "
                   "cover --file <img>. Then confirm-outline.",
              current_phase=data.get("phase"))
    pages = data.get("pages", [])
    start_idx = 1 if len(pages) > 1 else 0
    data["current_page_index"] = start_idx
    data["phase"] = "illustrating"
    _write_book(args.dir, data)
    brief = _page_brief(pages[start_idx])
    brief.update({
        "ok": True, "phase": "illustrating",
        "total_pages": len(pages),
        "next_action": "AUTO-LOOP from this page to the last WITHOUT pausing: "
                       "for each page run compose-prompt → generate image → "
                       "save-image → next; report one line of progress per "
                       "page. On generation failure run `regenerate` (logs the "
                       "attempt) and retry; after 3 failures suggest `skip`. "
                       "When next says all_done, run `finalize`.",
    })
    _emit(brief)


def cmd_next(args):
    data = _load_book(args.dir)
    _require_phase(data, "illustrating")
    pages = data.get("pages", [])
    if not pages:
        _fail("no pages — save-outline first")
    next_idx = int(data.get("current_page_index", 0)) + 1
    data["current_page_index"] = next_idx
    _write_book(args.dir, data)
    if next_idx >= len(pages):
        _emit({
            "ok": True, "all_done": True, "total_pages": len(pages),
            "next_action": "All pages illustrated. Run `finalize` to deliver "
                           "(validates every page, sets phase=delivered, and "
                           "exports the HTML).",
        })
    brief = _page_brief(pages[next_idx])
    brief.update({
        "ok": True, "all_done": False,
        "page_index": next_idx, "total_pages": len(pages),
        "next_action": "Illustrate this page now: compose-prompt --page %s "
                       "[--characters <names-on-this-page>] → generate → "
                       "save-image → next. Do NOT pause for user confirmation "
                       "during the auto loop." % brief["page_id"],
    })
    _emit(brief)


def cmd_amend_outline(args):
    data = _load_book(args.dir)
    _require_phase(data, "awaiting_outline_confirm")
    data["phase"] = "outlining"
    _write_book(args.dir, data)
    _emit({
        "ok": True, "phase": "outlining",
        "next_action": "Regenerate the FULL outline with the user's "
                       "corrections applied, then run save-outline again. "
                       "To KEEP existing images, carry each page's current "
                       "image_file value into the new outline JSON (get them "
                       "via status); pages whose image_prompt you changed "
                       "should omit image_file so they get re-illustrated. "
                       "If style changed, regenerate the cover too.",
    })


_AMEND_KEYS = ("narration", "page_title", "image_prompt")


def cmd_amend_page(args):
    data = _load_book(args.dir)
    _require_phase(data, "illustrating", "delivered")
    pid = (args.page or "").strip()
    page = _find_page(data, pid)
    try:
        patch = json.loads(args.json)
    except Exception as exc:
        _fail("--json is not valid JSON: %s" % exc,
              hint='Example: --json \'{"narration": {"zh": "...", "en": "..."}, '
                   '"image_prompt": "..."}\'')
    if not isinstance(patch, dict) or not patch:
        _fail("--json must be a non-empty object")
    unknown = [k for k in patch if k not in _AMEND_KEYS]
    if unknown:
        _fail("unknown fields: %s" % unknown,
              hint="Allowed: narration, page_title, image_prompt.")
    prompt_changed = False
    if "narration" in patch:
        nar = patch["narration"]
        if not isinstance(nar, dict):
            _fail("narration must be a dict with zh/en keys")
        merged = dict(page.get("narration", {}))
        merged.update({k: (v or "").strip() for k, v in nar.items() if k in ("zh", "en")})
        if not merged.get("zh") or not merged.get("en"):
            _fail("narration.zh and narration.en must both stay non-empty")
        page["narration"] = merged
    if "page_title" in patch:
        pt = patch["page_title"]
        if not isinstance(pt, dict):
            _fail("page_title must be a dict with zh/en keys")
        merged = dict(page.get("page_title", {}))
        merged.update({k: (v or "").strip() for k, v in pt.items() if k in ("zh", "en")})
        zh = merged.get("zh", "")
        if page.get("page_no", 0) != 0 and (len(zh) < 2 or len(zh) > 15):
            _fail("page_title.zh must be 2-15 chars (got %d)" % len(zh))
        page["page_title"] = merged
    if "image_prompt" in patch:
        ipr = (patch["image_prompt"] or "").strip()
        if not ipr:
            _fail("image_prompt cannot be emptied")
        if len(ipr) > 200:
            _fail("image_prompt too long (%d chars, max 200)" % len(ipr))
        if ipr != page.get("image_prompt"):
            page["image_prompt"] = ipr
            prompt_changed = True
            if pid == "cover":
                data.setdefault("cover", {})["image_prompt"] = ipr
    _write_book(args.dir, data)
    if prompt_changed:
        nxt = ("image_prompt changed → the old picture no longer matches. Run "
               "`regenerate --page %s`, re-illustrate (compose-prompt → "
               "generate → save-image), then `export`." % pid)
    else:
        nxt = "Text-only change — keep the existing image. Re-run `export` to refresh the HTML."
    _emit({"ok": True, "page_id": pid, "next_action": nxt})


def cmd_regenerate(args):
    data = _load_book(args.dir)
    _require_phase(data, "illustrating", "delivered")
    pid = (args.page or "").strip()
    page = _find_page(data, pid)
    page["image_file"] = ""
    page["failed_attempts"] = int(page.get("failed_attempts", 0)) + 1
    if data["pages"] and data["pages"][0].get("id") == pid:
        data.setdefault("cover", {})["image_file"] = ""
    _write_book(args.dir, data)
    attempts = page["failed_attempts"]
    hint = ("Image cleared (attempt #%d). Re-illustrate: compose-prompt --page "
            "%s → generate → save-image." % (attempts, pid))
    if attempts >= 3:
        hint += (" 3+ attempts failed — suggest `skip --page %s --reason ...` "
                 "to the user instead of retrying forever." % pid)
    _emit({"ok": True, "page_id": pid, "failed_attempts": attempts,
           "next_action": hint})


def cmd_skip(args):
    data = _load_book(args.dir)
    _require_phase(data, "illustrating")
    pid = (args.page or "").strip()
    page = _find_page(data, pid)
    page["image_file"] = SKIP_SENTINEL
    if (args.reason or "").strip():
        page["skip_reason"] = args.reason.strip()
    remaining = sum(1 for p in data["pages"] if not (p.get("image_file") or "").strip())
    _write_book(args.dir, data)
    if remaining > 0:
        nxt = ("Page skipped with a placeholder (narration preserved). %d "
               "pages still need images — continue via `next`." % remaining)
    else:
        nxt = "Page skipped. All pages now have images or placeholders — run `finalize`."
    _emit({"ok": True, "page_id": pid, "skipped": True, "remaining": remaining,
           "next_action": nxt})


_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".webp": "image/webp"}


def _image_ref(book_dir, image_file, inline):
    """Resolve a page's image_file to a viewer src (data URI / relative path).

    Empty or sentinel values resolve to "" — the viewer renders its own
    placeholder; the sentinel string never leaks into the HTML (FDA
    _clean_image_url parity).
    """
    val = (image_file or "").strip()
    if not val or val == SKIP_SENTINEL:
        return ""
    if not inline:
        return val
    path = Path(book_dir) / val
    if not path.is_file():
        return ""
    import base64
    mime = _MIME.get(path.suffix.lower(), "image/png")
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def _do_export(book_dir, data, inline):
    template = Path(__file__).resolve().parents[1] / "assets" / "viewer.template.html"
    if not template.is_file():
        _fail("viewer template missing: %s" % template,
              hint="The skill install is incomplete — re-install the whole "
                   "storybook-skill directory.")
    payload = {
        "title": data.get("title", {}),
        "author": data.get("author", ""),
        "style": data.get("style", ""),
        "story_note": data.get("story_note", ""),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages": [{
            "page_no": p.get("page_no", 0),
            "page_title": p.get("page_title", {}),
            "narration": p.get("narration", {}),
            "image": _image_ref(book_dir, p.get("image_file"), inline),
        } for p in data.get("pages", [])],
    }
    html = template.read_text(encoding="utf-8")
    title_zh = (data.get("title", {}) or {}).get("zh", "") or "storybook"
    # </script> guard: keep the embedded JSON from terminating its own tag.
    book_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("__TITLE__", title_zh).replace("__BOOK_JSON__", book_json)
    slug = Path(book_dir).resolve().name
    out_path = Path(book_dir) / ("%s.html" % slug)
    tmp = out_path.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def cmd_finalize(args):
    data = _load_book(args.dir)
    _require_phase(data, "illustrating")
    missing = [p.get("id", "?") for p in data.get("pages", [])
               if not (p.get("image_file") or "").strip()]
    if missing:
        _fail("以下页面缺少插画: %s" % ", ".join(missing),
              hint="这些页面还没生成图片。补图(compose-prompt → 生成 → "
                   "save-image),或对反复失败的页面用 skip。补齐后再 finalize。",
              current_phase=data.get("phase"))
    data["phase"] = "delivered"
    _write_book(args.dir, data)
    out_path = _do_export(args.dir, data, inline=True)
    _emit({
        "ok": True, "phase": "delivered",
        "page_count": len(data.get("pages", [])),
        "html": str(out_path.resolve()),
        "next_action": "Book delivered! Give the user the HTML path "
                       "(double-click to open; Print = PDF). Later revisions: "
                       "amend-page / regenerate → save-image → export.",
    })


def cmd_export(args):
    data = _load_book(args.dir)
    _require_phase(data, "awaiting_outline_confirm", "illustrating", "delivered")
    inline = not args.link_images
    out_path = _do_export(args.dir, data, inline)
    _emit({
        "ok": True, "html": str(out_path.resolve()),
        "size_bytes": out_path.stat().st_size, "inline_images": inline,
        "next_action": "Tell the user the absolute HTML path — double-click "
                       "to open; browser Print = PDF. Re-run export after any "
                       "later amendment.",
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
    phase = data.get("phase", "")
    pages = data.get("pages", [])
    rows = []
    done = skipped = 0
    for p in pages:
        img = (p.get("image_file") or "").strip()
        is_skipped = img == SKIP_SENTINEL
        is_done = bool(img)
        if is_skipped:
            skipped += 1
        if is_done:
            done += 1
        rows.append({
            "page_id": p.get("id", ""), "page_no": p.get("page_no", 0),
            "done": is_done, "skipped": is_skipped,
            "failed_attempts": int(p.get("failed_attempts", 0)),
            "image_file": "" if is_skipped else img,
        })
    cover_ok = bool((data.get("cover", {}).get("image_file") or "").strip())
    if phase == "outlining":
        nxt = "Write the outline (5-12 pages incl cover) and run save-outline."
    elif phase == "awaiting_outline_confirm":
        if not cover_ok:
            nxt = ("Generate the cover (compose-prompt --page cover → image "
                   "tool → save-image --page cover), show outline+cover, then "
                   "WAIT for user confirmation before confirm-outline.")
        else:
            nxt = ("Show the user the outline + cover and WAIT for explicit "
                   "confirmation; then confirm-outline (or amend-outline).")
    elif phase == "illustrating":
        pending = [r["page_id"] for r in rows if not r["done"]]
        if pending:
            nxt = ("Auto-loop the remaining pages %s: compose-prompt → "
                   "generate → save-image → next; then finalize." % pending)
        else:
            nxt = "All pages have images. Run finalize."
    elif phase == "delivered":
        nxt = ("Book is delivered. Revisions: amend-page / regenerate → "
               "save-image → export. The HTML lives next to book.json.")
    else:
        nxt = "Unknown phase %r — book.json may be hand-edited; restore from .bak." % phase
    html = Path(book_dir) / (Path(book_dir).resolve().name + ".html")
    _emit({
        "ok": True, "exists": True, "phase": phase,
        "title": data.get("title", {}), "idea": data.get("idea", ""),
        "audience": data.get("audience", ""), "style": data.get("style", ""),
        "author": data.get("author", ""),
        "cover_done": cover_ok,
        "pages_total": len(pages), "pages_done": done, "pages_skipped": skipped,
        "current_page_index": int(data.get("current_page_index", 0)),
        "pages": rows,
        "html_exists": html.is_file(),
        "next_action": nxt,
    })


def cmd_doctor(args):
    import os
    py_ok = sys.version_info >= (3, 9)
    template = Path(__file__).resolve().parents[1] / "assets" / "viewer.template.html"
    report = {
        "ok": True,
        "python_version": "%d.%d.%d" % sys.version_info[:3],
        "python_ok": py_ok,
        "viewer_template_ok": template.is_file(),
        "image_api_key_set": bool(os.environ.get("STORYBOOK_IMAGE_API_KEY")),
        "image_base_url": os.environ.get("STORYBOOK_IMAGE_BASE_URL",
                                         "https://api.openai.com/v1"),
        "image_model": os.environ.get("STORYBOOK_IMAGE_MODEL", "gpt-image-1"),
        "image_size": os.environ.get("STORYBOOK_IMAGE_SIZE", "1024x1536"),
    }
    notes = []
    if not py_ok:
        notes.append("python >= 3.9 required")
    if not report["image_api_key_set"]:
        notes.append("STORYBOOK_IMAGE_API_KEY unset — fallback image generation "
                     "(scripts/gen_image.py) unavailable; the host agent's own "
                     "image tool can still be used")
    report["notes"] = notes
    _emit(report)


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

    p = sub.add_parser("compose-prompt",
                       help="Assemble the full image prompt for one page.")
    p.add_argument("--page", required=True)
    p.add_argument("--characters", default="",
                   help="character NAMES on this page, comma-separated")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_compose_prompt)

    p = sub.add_parser("save-image", help="Register a generated image for a page.")
    p.add_argument("--page", required=True, help="cover | page-N")
    p.add_argument("--file", required=True, help="path of the generated image")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_save_image)

    p = sub.add_parser("confirm-outline",
                       help="User confirmed outline+cover → illustrating.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_confirm_outline)

    p = sub.add_parser("amend-outline", help="Back to outlining for a rewrite.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_amend_outline)

    p = sub.add_parser("amend-page", help="Patch one page's text fields.")
    p.add_argument("--page", required=True)
    p.add_argument("--json", required=True,
                   help='partial JSON: {"narration": {...}, "page_title": {...}, "image_prompt": "..."}')
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_amend_page)

    p = sub.add_parser("regenerate", help="Clear a page image for re-illustration.")
    p.add_argument("--page", required=True)
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_regenerate)

    p = sub.add_parser("skip", help="Skip a repeatedly-failing page.")
    p.add_argument("--page", required=True)
    p.add_argument("--reason", default="")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_skip)

    p = sub.add_parser("next", help="Advance illustration cursor.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("save-outline", help="Persist the validated outline.")
    p.add_argument("--file", required=True, help="outline JSON path, or - for stdin")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_save_outline)

    p = sub.add_parser("finalize", help="Validate, deliver, and export.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_finalize)

    p = sub.add_parser("export", help="Render the self-contained HTML book.")
    p.add_argument("--link-images", action="store_true",
                   help="reference images/ by relative path instead of inlining base64")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("status", help="Phase, progress, and next action.")
    p.add_argument("--dir", default=".")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("doctor", help="Environment self-check.")
    p.set_defaults(func=cmd_doctor)

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
