from __future__ import annotations

import unittest
from pathlib import Path

import helpers


class TestGenImage(unittest.TestCase):
    def test_missing_key_fails_fast(self):
        with helpers.tmp() as td:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen("--prompt", "a fox", "--out", out_png)
            self.assertEqual(code, 2)
            self.assertIn("STORYBOOK_IMAGE_API_KEY", out["hint"])

    def test_b64_response_writes_png(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="b64") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 0)
            self.assertEqual(out_png.read_bytes(), helpers.TINY_PNG)

    def test_url_response_downloads(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="url") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 0)
            self.assertEqual(out_png.read_bytes(), helpers.TINY_PNG)

    def test_retries_on_5xx_then_succeeds(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="b64", fail_times=2) as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url,
                           "STORYBOOK_IMAGE_RETRY_BASE_SLEEP": "0"})
            self.assertEqual(code, 0)
            self.assertEqual(api.posts, 3)

    def test_prompt_file_stdin(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="b64") as api:
            pf = Path(td) / "p.txt"
            pf.write_text("a fox under the moon", encoding="utf-8")
            out_png = Path(td) / "o.png"
            code, _, _ = helpers.run_gen(
                "--prompt-file", pf, "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
