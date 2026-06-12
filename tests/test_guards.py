from __future__ import annotations

import json
import unittest
from pathlib import Path

import helpers


def outline_payload(n_body=4, **overrides):
    """Valid save-outline input; pages[0] is the cover (FDA convention)."""
    pages = [{
        "page_no": 0,
        "narration": {"zh": "封面", "en": "Cover"},
        "image_prompt": "fox under moon, title mood, weight upper two thirds",
    }]
    for i in range(1, n_body + 1):
        pages.append({
            "page_no": i,
            "page_title": {"zh": "第%d页的标题" % i, "en": "Title %d" % i},
            "narration": {"zh": "嗖——第%d页。" % i, "en": "Whoosh %d." % i},
            "image_prompt": "fox walks, scene %d" % i,
        })
    payload = {
        "title": {"zh": "小狐狸找月亮", "en": "Little Fox Seeks the Moon"},
        "author": "lxy", "story_note": "观察与坚持。",
        "style_bible": "Soft watercolor, warm palette.",
        "character_bible": "Little Fox: red fur, amber eyes.",
        "pages": pages,
    }
    payload.update(overrides)
    return payload


def save_outline(book_dir, payload):
    f = Path(book_dir).parent / "outline.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return helpers.run_cli("save-outline", "--file", f, "--dir", book_dir)


class TestSaveOutlineValidation(unittest.TestCase):
    def _fresh(self, td):
        _, out, _ = helpers.run_cli("init", "--idea", "fox", "--slug", "b", "--dir", td)
        return out["book_dir"]

    def test_happy_path_assigns_ids_and_advances_phase(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            code, out, _ = save_outline(d, outline_payload())
            self.assertEqual(code, 0)
            self.assertEqual(out["page_count"], 5)
            data = helpers.read_book(d)
            self.assertEqual(data["phase"], "awaiting_outline_confirm")
            self.assertEqual(data["pages"][0]["id"], "cover")
            self.assertEqual(data["pages"][1]["id"], "page-1")
            self.assertEqual(data["cover"]["image_prompt"],
                             data["pages"][0]["image_prompt"])
            self.assertIn("cover", out["next_action"])  # 先出封面再请确认

    def test_too_few_pages_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            code, out, _ = save_outline(d, outline_payload(n_body=3))
            self.assertEqual(code, 2)
            self.assertIn("at least 5", out["error"])

    def test_too_many_pages_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            code, out, _ = save_outline(d, outline_payload(n_body=12))  # 13 total
            self.assertEqual(code, 2)
            self.assertIn("at most 12", out["error"])

    def test_long_image_prompt_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][2]["image_prompt"] = "x" * 201
            code, out, _ = save_outline(d, p)
            self.assertEqual(code, 2)
            self.assertIn("image_prompt too long", out["error"])

    def test_missing_body_page_title_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][1]["page_title"] = {"zh": "", "en": "T"}
            code, out, _ = save_outline(d, p)
            self.assertEqual(code, 2)

    def test_bad_zh_title_length_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][1]["page_title"]["zh"] = "一"  # 1 char < 2
            code, out, _ = save_outline(d, p)
            self.assertEqual(code, 2)
            self.assertIn("2-15", out["error"])

    def test_noncontiguous_page_no_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][2]["page_no"] = 9
            code, out, _ = save_outline(d, p)
            self.assertEqual(code, 2)
            self.assertIn("page_no", out["error"])

    def test_missing_narration_lang_rejected(self):
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][3]["narration"]["en"] = ""
            code, out, _ = save_outline(d, p)
            self.assertEqual(code, 2)

    def test_wrong_phase_rejected_with_hint(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            code, out, _ = save_outline(d, outline_payload())
            self.assertEqual(code, 2)
            self.assertEqual(out["current_phase"], "illustrating")
            self.assertIn("save-outline", out["error"] + out.get("hint", ""))

    def test_resave_preserves_carried_image_file(self):
        # amend 流程:agent 回填已有 image_file → 封面图复用(host SKILL 规则)
        with helpers.tmp() as td:
            d = self._fresh(td)
            p = outline_payload()
            p["pages"][0]["image_file"] = "images/cover.png"
            code, _, _ = save_outline(d, p)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][0]["image_file"], "images/cover.png")
            self.assertEqual(data["cover"]["image_file"], "images/cover.png")


class TestSaveImageGuards(unittest.TestCase):
    def test_body_page_locked_in_awaiting(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")
            src = Path(td) / "x.png"
            src.write_bytes(helpers.TINY_PNG)
            code, out, _ = helpers.run_cli("save-image", "--page", "page-1",
                                           "--file", src, "--dir", d)
            self.assertEqual(code, 2)
            self.assertIn("awaiting_outline_confirm", out["hint"])
            self.assertIn("confirm-outline", out["hint"])
            self.assertEqual(helpers.read_book(d)["pages"][1]["image_file"], "")

    def test_unknown_page_404_lists_available(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            src = Path(td) / "x.png"
            src.write_bytes(helpers.TINY_PNG)
            code, out, _ = helpers.run_cli("save-image", "--page", "page-99",
                                           "--file", src, "--dir", d)
            self.assertEqual(code, 2)
            self.assertIn("page-1", out["hint"])

    def test_bad_extension_rejected(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            src = Path(td) / "x.gif"
            src.write_bytes(b"GIF89a")
            code, out, _ = helpers.run_cli("save-image", "--page", "page-1",
                                           "--file", src, "--dir", d)
            self.assertEqual(code, 2)
            self.assertIn("png", out["hint"])


class TestConfirmOutline(unittest.TestCase):
    def test_blocked_without_cover_image(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")  # 无图
            code, out, _ = helpers.run_cli("confirm-outline", "--dir", d)
            self.assertEqual(code, 2)
            self.assertIn("cover", out["error"].lower())
            self.assertIn("save-image", out["hint"])

    def test_wrong_phase_blocked(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="outlining")
            code, _, _ = helpers.run_cli("confirm-outline", "--dir", d)
            self.assertEqual(code, 2)


class TestAmendGuards(unittest.TestCase):
    def test_skip_blocked_in_delivered(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, _, _ = helpers.run_cli("skip", "--page", "page-1", "--dir", d)
            self.assertEqual(code, 2)

    def test_amend_outline_blocked_in_illustrating(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            code, _, _ = helpers.run_cli("amend-outline", "--dir", d)
            self.assertEqual(code, 2)

    def test_amend_page_bad_json_rejected(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, _, _ = helpers.run_cli("amend-page", "--page", "page-1",
                                         "--json", "not json", "--dir", d)
            self.assertEqual(code, 2)


class TestGuardMatrix(unittest.TestCase):
    """Every state-changing command refuses every disallowed phase with exit 2."""

    MATRIX = [
        # (argv-builder, allowed phases)
        (lambda d: ["save-outline", "--file", "-", "--dir", d], {"outlining"}),
        (lambda d: ["amend-outline", "--dir", d], {"awaiting_outline_confirm"}),
        (lambda d: ["confirm-outline", "--dir", d], {"awaiting_outline_confirm"}),
        (lambda d: ["next", "--dir", d], {"illustrating"}),
        (lambda d: ["skip", "--page", "page-1", "--dir", d], {"illustrating"}),
        (lambda d: ["finalize", "--dir", d], {"illustrating"}),
        (lambda d: ["amend-page", "--page", "page-1", "--json", "{}", "--dir", d],
         {"illustrating", "delivered"}),
        (lambda d: ["regenerate", "--page", "page-1", "--dir", d],
         {"illustrating", "delivered"}),
        (lambda d: ["compose-prompt", "--page", "page-1", "--dir", d],
         {"illustrating", "delivered"}),
        (lambda d: ["export", "--dir", d],
         {"awaiting_outline_confirm", "illustrating", "delivered"}),
    ]

    def test_matrix(self):
        import itertools
        phases = ["outlining", "awaiting_outline_confirm", "illustrating", "delivered"]
        for (build, allowed), phase in itertools.product(self.MATRIX, phases):
            if phase in allowed:
                continue
            with helpers.tmp() as td:
                d = helpers.make_book(td, phase=phase, with_images=True)
                code, out, _ = helpers.run_cli(*build(str(d)))
                self.assertEqual(
                    code, 2,
                    "argv=%s phase=%s expected guard, got %s" % (build(str(d)), phase, out))
                self.assertEqual(out.get("current_phase"), phase)
