from __future__ import annotations

import json
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

    def _env(self, api):
        return {"STORYBOOK_IMAGE_API_KEY": "k",
                "STORYBOOK_IMAGE_BASE_URL": api.base_url,
                "STORYBOOK_IMAGE_RETRY_BASE_SLEEP": "0"}

    def test_error_200_body_is_surfaced(self):
        # I5-A: 200 with {"error":{...}} must report the provider's reason,
        # not the generic "neither b64 nor url".
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="apierror") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png, env_extra=self._env(api))
            self.assertEqual(code, 2)
            self.assertIn("content policy", json.dumps(out))
            self.assertFalse(out_png.exists())

    def test_empty_data_list_fails(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="empty") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png, env_extra=self._env(api))
            self.assertEqual(code, 2)
            self.assertFalse(out_png.exists())

    def test_non_image_response_rejected_and_no_file(self):
        # I4: a 200 carrying non-image bytes must NOT land on disk as a PNG.
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="notimage") as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png, env_extra=self._env(api))
            self.assertEqual(code, 2)
            self.assertIn("not a PNG/JPEG/WebP", out["error"])
            self.assertFalse(out_png.exists())
            self.assertFalse((Path(td) / "o.png.tmp").exists())

    def test_retry_exhausted_after_3_attempts(self):
        with helpers.tmp() as td, helpers.FakeImageAPI(mode="b64", fail_times=3) as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png, env_extra=self._env(api))
            self.assertEqual(code, 2)
            self.assertIn("3 attempts", out["error"])
            self.assertEqual(api.posts, 3)

    def test_4xx_fails_fast_without_retry(self):
        # A 4xx is a client error — retrying can't help, so don't.
        with helpers.tmp() as td, helpers.FakeImageAPI(client_error=400) as api:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "a fox", "--out", out_png, env_extra=self._env(api))
            self.assertEqual(code, 2)
            self.assertEqual(api.posts, 1)

    def test_empty_prompt_rejected_before_http(self):
        # P2: a whitespace-only prompt must fail fast, never hit the provider.
        with helpers.tmp() as td:
            out_png = Path(td) / "o.png"
            code, out, _ = helpers.run_gen(
                "--prompt", "   ", "--out", out_png,
                env_extra={"STORYBOOK_IMAGE_API_KEY": "k"})
            self.assertEqual(code, 2)
            self.assertIn("empty", out["error"])
            self.assertFalse(out_png.exists())


if __name__ == "__main__":
    unittest.main()
