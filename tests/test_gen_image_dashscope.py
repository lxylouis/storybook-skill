from __future__ import annotations

import unittest
from pathlib import Path

import helpers


class TestGenImageDashScope(unittest.TestCase):
    def test_missing_key_fails_fast(self):
        with helpers.tmp() as td:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds("--prompt", "a fox", "--out", out_png)
            self.assertEqual(code, 2)
            self.assertIn("STORYBOOK_IMAGE_API_KEY", out["hint"])

    def test_happy_path_downloads_image_url(self):
        with helpers.tmp() as td, helpers.FakeDashScopeAPI() as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 0)
            self.assertEqual(out_png.read_bytes(), helpers.TINY_PNG)
            self.assertEqual(out["size"], "1024×1536")  # x → × 规范化

    def test_api_level_error_is_reported(self):
        with helpers.tmp() as td, helpers.FakeDashScopeAPI(mode="apierror") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 2)
            self.assertIn("InvalidParameter", out["error"])

    def test_size_out_of_range_rejected_before_http(self):
        with helpers.tmp() as td:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png, "--size", "512x512",
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": "http://127.0.0.1:9/api/v1"})
            self.assertEqual(code, 2)
            self.assertIn("768", out["hint"])

    def test_retries_on_5xx_then_succeeds(self):
        with helpers.tmp() as td, helpers.FakeDashScopeAPI(fail_times=2) as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url,
                           "STORYBOOK_IMAGE_RETRY_BASE_SLEEP": "0"})
            self.assertEqual(code, 0)
            self.assertEqual(api.posts, 3)

    def test_unexpected_structure_is_reported(self):
        # I5-B: a 200 dict with no usable output.choices[].image must take the
        # structured _fail path (not crash) — previously untested.
        with helpers.tmp() as td, helpers.FakeDashScopeAPI(mode="badshape") as api:
            out_png = Path(td) / "o.png"
            code, out, err = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url})
            self.assertEqual(code, 2)
            self.assertIn("unexpected DashScope response structure", out["error"])
            self.assertNotIn("Traceback", err)
            self.assertFalse(out_png.exists())

    def test_non_image_download_rejected_and_no_file(self):
        # I4: a valid-looking response whose image URL returns a non-image body
        # must not be written to disk as a PNG.
        with helpers.tmp() as td, helpers.FakeDashScopeAPI(bad_image=True) as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "a fox", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url,
                           "STORYBOOK_IMAGE_RETRY_BASE_SLEEP": "0"})
            self.assertEqual(code, 2)
            self.assertIn("not a PNG/JPEG/WebP", out["error"])
            self.assertFalse(out_png.exists())
            self.assertFalse((Path(td) / "o.png.tmp").exists())

    def test_empty_prompt_rejected_before_http(self):
        # P2: a whitespace-only prompt must fail fast, never hit DashScope.
        with helpers.tmp() as td:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt", "   ", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k"})
            self.assertEqual(code, 2)
            self.assertIn("empty", out["error"])
            self.assertFalse(out_png.exists())

    def test_size_normalization_variants(self):
        # P2: every accepted spelling maps to DashScope's W×H (or a preset),
        # and a non-WxH string falls through untouched for the API to judge.
        cases = [("1024x1536", "1024×1536"), ("1024×1536", "1024×1536"),
                 ("1024*1536", "1024×1536"), ("1024X1536", "1024×1536"),
                 ("2K", "2K"), ("portrait", "portrait")]
        for given, want in cases:
            with helpers.tmp() as td, helpers.FakeDashScopeAPI() as api:
                out_png = Path(td) / "o.png"
                code, out, _ = helpers.run_gen_ds(
                    "--prompt", "a fox", "--out", out_png, "--size", given,
                    env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                               "STORYBOOK_IMAGE_BASE_URL": api.base_url})
                self.assertEqual(code, 0, "%s: %s" % (given, out))
                self.assertEqual(out["size"], want, "size %r" % given)

    def test_prompt_file_stdin(self):
        # P2: the `--prompt-file -` stdin path (had no coverage on this side).
        with helpers.tmp() as td, helpers.FakeDashScopeAPI() as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen_ds(
                "--prompt-file", "-", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k",
                           "STORYBOOK_IMAGE_BASE_URL": api.base_url},
                stdin="a fox under the moon")
            self.assertEqual(code, 0)
            self.assertEqual(out_png.read_bytes(), helpers.TINY_PNG)


if __name__ == "__main__":
    unittest.main()
