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


if __name__ == "__main__":
    unittest.main()
