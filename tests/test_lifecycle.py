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


if __name__ == "__main__":
    unittest.main()
