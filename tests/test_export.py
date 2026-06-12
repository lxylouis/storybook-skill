from __future__ import annotations

import unittest
from pathlib import Path

import helpers


class TestExport(unittest.TestCase):
    def test_inline_export_embeds_everything(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn("data:image/png;base64,", html)
            self.assertIn("小狐狸找月亮", html)
            self.assertIn("Little Fox Seeks the Moon", html)
            self.assertIn("嗖——第1页。", html)          # zh narration
            self.assertIn("Whoosh — page 4.", html)     # en narration
            self.assertIn("speechSynthesis", html)      # 朗读
            self.assertIn("@media print", html)         # 打印
            self.assertNotIn("__BOOK_JSON__", html)     # 占位符全部替换

    def test_link_mode_references_relative_paths(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--link-images", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn("images/page-01.png", html)
            self.assertNotIn("data:image/png;base64,", html)

    def test_skipped_page_renders_placeholder_not_sentinel(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="illustrating", with_images=True)
            data = helpers.read_book(d)
            data["pages"][2]["image_file"] = "skipped"
            helpers.write_book(d, data)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertNotIn('"skipped"', html.split("book-data")[1].split("</script>")[0])

    def test_export_blocked_in_outlining(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="outlining")
            code, _, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 2)
