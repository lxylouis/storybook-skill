from __future__ import annotations

import unittest
from pathlib import Path

import helpers


class TestStatusEmpty(unittest.TestCase):
    def test_status_without_book_json(self):
        with helpers.tmp() as td:
            code, out, _ = helpers.run_cli("status", "--dir", td)
            self.assertEqual(code, 0)
            self.assertFalse(out["exists"])
            self.assertIn("init", out["next_action"])


class TestInit(unittest.TestCase):
    def test_init_creates_book(self):
        with helpers.tmp() as td:
            code, out, _ = helpers.run_cli(
                "init", "--idea", "Little fox seeks the moon!",
                "--audience", "3-6岁", "--style", "watercolor",
                "--author", "lxy", "--dir", td)
            self.assertEqual(code, 0)
            self.assertEqual(out["slug"], "little-fox-seeks-the-moon")
            book_dir = out["book_dir"]
            data = helpers.read_book(book_dir)
            self.assertEqual(data["phase"], "outlining")
            self.assertEqual(data["idea"], "Little fox seeks the moon!")
            self.assertEqual(data["pages"], [])
            import os
            self.assertTrue(os.path.isdir(os.path.join(book_dir, "images")))
            self.assertIn("save-outline", out["next_action"])

    def test_init_cjk_idea_falls_back_to_book_slug(self):
        with helpers.tmp() as td:
            code, out, _ = helpers.run_cli("init", "--idea", "小狐狸找月亮", "--dir", td)
            self.assertEqual(code, 0)
            self.assertEqual(out["slug"], "book")

    def test_init_refuses_existing_dir(self):
        with helpers.tmp() as td:
            helpers.run_cli("init", "--idea", "fox", "--slug", "same", "--dir", td)
            code, out, _ = helpers.run_cli("init", "--idea", "fox", "--slug", "same", "--dir", td)
            self.assertEqual(code, 2)
            self.assertIn("exists", out["error"])

    def test_init_rejects_bad_slug(self):
        with helpers.tmp() as td:
            code, out, _ = helpers.run_cli("init", "--idea", "fox", "--slug", "团 bad/slug", "--dir", td)
            self.assertEqual(code, 2)


class TestSaveImage(unittest.TestCase):
    def test_save_cover_in_awaiting_phase(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")
            src = Path(td) / "gen.png"
            src.write_bytes(helpers.TINY_PNG)
            code, out, _ = helpers.run_cli("save-image", "--page", "cover",
                                           "--file", src, "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][0]["image_file"], "images/cover.png")
            self.assertEqual(data["cover"]["image_file"], "images/cover.png")
            self.assertTrue((Path(d) / "images" / "cover.png").is_file())
            self.assertEqual(out["remaining"], 4)

    def test_save_body_page_normalizes_filename(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            src = Path(td) / "weird name.JPEG"
            src.write_bytes(helpers.TINY_PNG)
            code, out, _ = helpers.run_cli("save-image", "--page", "page-2",
                                           "--file", src, "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][2]["image_file"], "images/page-02.jpeg")

    def test_save_image_resets_failed_attempts(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            data = helpers.read_book(d)
            data["pages"][1]["failed_attempts"] = 2
            helpers.write_book(d, data)
            src = Path(td) / "ok.png"
            src.write_bytes(helpers.TINY_PNG)
            helpers.run_cli("save-image", "--page", "page-1", "--file", src, "--dir", d)
            self.assertEqual(helpers.read_book(d)["pages"][1]["failed_attempts"], 0)


class TestComposePrompt(unittest.TestCase):
    def test_cover_allowed_in_awaiting(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")
            code, out, _ = helpers.run_cli("compose-prompt", "--page", "cover", "--dir", d)
            self.assertEqual(code, 0)
            self.assertLessEqual(out["prompt_len"], 500)
            self.assertIn("no text or captions", out["prompt"])

    def test_body_page_blocked_in_awaiting(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")
            code, out, _ = helpers.run_cli("compose-prompt", "--page", "page-1", "--dir", d)
            self.assertEqual(code, 2)

    def test_characters_filter_injects_full_entry(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            code, out, _ = helpers.run_cli("compose-prompt", "--page", "page-1",
                                           "--characters", "Little Fox", "--dir", d)
            self.assertEqual(code, 0)
            self.assertIn("red fur, amber eyes", out["prompt"])
            self.assertNotIn("Moon Granny", out["prompt"])

    def test_unmatched_names_fall_back_to_full_bible(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            code, out, _ = helpers.run_cli("compose-prompt", "--page", "page-1",
                                           "--characters", "不存在的角色", "--dir", d)
            self.assertEqual(code, 0)
            self.assertIn("red fur, amber eyes", out["prompt"])

    def test_truncation_keeps_total_under_500(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            data = helpers.read_book(d)
            data["style_bible"] = "S" * 400
            data["character_bible"] = "C" * 400
            data["pages"][1]["image_prompt"] = "p" * 200
            helpers.write_book(d, data)
            code, out, _ = helpers.run_cli("compose-prompt", "--page", "page-1", "--dir", d)
            self.assertEqual(code, 0)
            self.assertLessEqual(out["prompt_len"], 500)


class TestConfirmAndNext(unittest.TestCase):
    def _confirmed(self, td):
        d = helpers.make_book(td, phase="awaiting_outline_confirm")
        data = helpers.read_book(d)
        data["pages"][0]["image_file"] = "images/cover.png"
        data["cover"]["image_file"] = "images/cover.png"
        helpers.write_book(d, data)
        (Path(d) / "images" / "cover.png").write_bytes(helpers.TINY_PNG)
        return d

    def test_confirm_starts_at_body_page_1(self):
        with helpers.tmp() as td:
            d = self._confirmed(td)
            code, out, _ = helpers.run_cli("confirm-outline", "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["phase"], "illustrating")
            self.assertEqual(data["current_page_index"], 1)
            self.assertEqual(out["page_id"], "page-1")  # 直接给出第一页数据

    def test_next_advances_and_finishes(self):
        with helpers.tmp() as td:
            d = self._confirmed(td)
            helpers.run_cli("confirm-outline", "--dir", d)
            code, out, _ = helpers.run_cli("next", "--dir", d)
            self.assertEqual(code, 0)
            self.assertFalse(out["all_done"])
            self.assertEqual(out["page_id"], "page-2")
            for _ in range(3):
                code, out, _ = helpers.run_cli("next", "--dir", d)
            self.assertTrue(out["all_done"])
            self.assertIn("finalize", out["next_action"])


class TestAmendRegenerateSkip(unittest.TestCase):
    def test_amend_outline_returns_to_outlining(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="awaiting_outline_confirm")
            code, out, _ = helpers.run_cli("amend-outline", "--dir", d)
            self.assertEqual(code, 0)
            self.assertEqual(helpers.read_book(d)["phase"], "outlining")
            self.assertIn("save-outline", out["next_action"])
            self.assertIn("image_file", out["next_action"])  # 提醒回填保图

    def test_amend_page_partial_override(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli(
                "amend-page", "--page", "page-2", "--json",
                '{"narration": {"zh": "哗啦——新的一页。", "en": "Splash — new page."}}',
                "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][2]["narration"]["zh"], "哗啦——新的一页。")
            self.assertEqual(data["pages"][2]["image_file"], "images/page-02.png")
            self.assertNotIn("regenerate", out["next_action"])  # 只改文不触发重出图

    def test_amend_page_image_prompt_hints_regenerate(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli(
                "amend-page", "--page", "page-2", "--json",
                '{"image_prompt": "fox jumps over a creek at dawn"}', "--dir", d)
            self.assertEqual(code, 0)
            self.assertIn("regenerate", out["next_action"])  # 改图才改图

    def test_amend_page_validates_fields(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli(
                "amend-page", "--page", "page-2", "--json",
                '{"image_prompt": "%s"}' % ("x" * 201), "--dir", d)
            self.assertEqual(code, 2)

    def test_regenerate_clears_image_and_counts(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating", with_images=True)
            code, out, _ = helpers.run_cli("regenerate", "--page", "cover", "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][0]["image_file"], "")
            self.assertEqual(data["cover"]["image_file"], "")  # cover 同步
            self.assertEqual(data["pages"][0]["failed_attempts"], 1)

    def test_skip_sets_sentinel(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating")
            code, out, _ = helpers.run_cli("skip", "--page", "page-3",
                                           "--reason", "content policy", "--dir", d)
            self.assertEqual(code, 0)
            data = helpers.read_book(d)
            self.assertEqual(data["pages"][3]["image_file"], "skipped")
            self.assertEqual(data["pages"][3]["skip_reason"], "content policy")


if __name__ == "__main__":
    unittest.main()
