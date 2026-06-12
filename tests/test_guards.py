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
