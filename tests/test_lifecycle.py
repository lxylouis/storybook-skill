from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
