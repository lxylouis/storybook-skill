from __future__ import annotations

import json
import unittest
import zipfile
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

    def test_zip_export_bundles_link_images_folder(self):
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--zip", "--dir", d)
            self.assertEqual(code, 0)
            self.assertEqual(out["delivery"], "zip")
            z = Path(out["zip"])
            self.assertTrue(z.is_file())
            slug = Path(d).resolve().name
            with zipfile.ZipFile(z) as zf:
                names = zf.namelist()
                idx = zf.read("%s/index.html" % slug).decode("utf-8")
            self.assertIn("%s/index.html" % slug, names)
            self.assertTrue(any(n.startswith("%s/images/" % slug) for n in names))
            self.assertIn("images/page-01.png", idx)          # relative ref
            self.assertNotIn("data:image/png;base64,", idx)   # zip ⇒ link mode

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

    def test_viewer_has_synced_reader_features(self):
        # Regression guard for the upstream reader UX synced into the viewer:
        # flip sound, A4 print sizing, decode-before-print, pointer swipe.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn("@page { size: A4 portrait", html)   # A4 print sizing
            self.assertIn("print-color-adjust: exact", html)
            self.assertIn("function playPageTurn", html)        # flip sound...
            self.assertIn("playPageTurn();", html)              # ...actually fired in go()
            self.assertIn("function printBook", html)           # decode-before-print
            self.assertIn("im.decode", html)
            self.assertIn("pointerdown", html)                  # pointer swipe
            self.assertIn("touch-action: pan-y", html)

    def test_viewer_has_recording_print_and_veil(self):
        # Second sync batch: 我自己读 recording, current-language print, flip veil.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn('id="recbtn"', html)                  # 我自己读 button
            self.assertIn("MediaRecorder", html)                # recording engine
            self.assertIn("function renderRecPanel", html)
            self.assertIn("function buildPrint(lang)", html)    # print follows current lang
            self.assertIn("buildPrint(state.lang)", html)
            self.assertIn("flipveil", html)                     # flip veil
            self.assertIn("function setVeil", html)

    def test_viewer_has_cinema_and_theater(self):
        # Standalone version of upstream Story Cinema / Story Theater:
        # auto-play whole book, camera performance, canvas compositing, video download.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn('id="cinemabtn"', html)
            self.assertIn('id="theaterbtn"', html)
            header = html.split("<header>", 1)[1].split("</header>", 1)[0]
            speakrow = html.split('id="speakrow"', 1)[1].split("</div>", 1)[0]
            self.assertIn('id="cinemabtn"', header)
            self.assertIn('id="theaterbtn"', header)
            self.assertLess(header.index('id="theaterbtn"'), header.index('id="printbtn"'))
            self.assertNotIn('id="cinemabtn"', speakrow)
            self.assertNotIn('id="theaterbtn"', speakrow)
            self.assertIn("function startCinema", html)
            self.assertIn("function renderPerfSetup", html)
            self.assertIn("function drawCompositeFrame", html)
            self.assertIn('id="th-finish"', html)
            self.assertIn("function waitForPerfVideoReady", html)
            self.assertIn("function resetPerfRecording", html)
            self.assertIn("function perfCanvasLayout", html)
            self.assertIn("function drawBookPanel", html)
            self.assertIn("function drawCameraPanel", html)
            self.assertIn("function perfRecorderOptions", html)
            self.assertIn("data-setup-layout", html)
            self.assertIn('["split", "pip", "stage"]', html)
            self.assertIn("if (startPerfRecorder(session))", html)
            self.assertIn("th-layout-choice", html)
            self.assertIn("recording: false, session: 0", html)
            self.assertIn("rec.onstop = function ()", html)
            self.assertIn("session !== perf.session", html)
            self.assertIn("perf.recorder.requestData()", html)
            self.assertIn("captureStream", html)
            self.assertIn("storybook-theater.webm", html)
            self.assertIn("max-height: calc(100dvh - 88px)", html)
            self.assertIn("overflow: hidden", html)
            self.assertIn("cinema-mode", html)
            self.assertIn('root.classList.toggle("cinema-mode"', html)


class TestExportSecurity(unittest.TestCase):
    """XSS hardening for the self-contained, shared-around HTML (C1 + I3)."""

    def test_outline_rejects_malicious_image_file(self):
        # C1 entry guard: a crafted image_file can't survive save-outline,
        # so the amend-outline round-trip can't smuggle it into book.json.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="outlining")
            outline = helpers.base_book(phase="outlining")
            outline["pages"][1]["image_file"] = 'images/x.png" onerror="alert(1)'
            f = Path(td) / "outline.json"
            f.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
            code, out, _ = helpers.run_cli("save-outline", "--file", str(f), "--dir", d)
            self.assertEqual(code, 2)
            self.assertIn("image_file", out.get("error", ""))

    def test_outline_accepts_clean_image_file(self):
        # Guard must not reject what save-image legitimately writes.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="outlining")
            outline = helpers.base_book(phase="outlining")
            outline["pages"][1]["image_file"] = "images/page-01.png"
            f = Path(td) / "outline.json"
            f.write_text(json.dumps(outline, ensure_ascii=False), encoding="utf-8")
            code, out, _ = helpers.run_cli("save-outline", "--file", str(f), "--dir", d)
            self.assertEqual(code, 0)
            self.assertEqual(helpers.read_book(d)["pages"][1]["image_file"],
                             "images/page-01.png")

    def test_viewer_sink_escapes_image_src(self):
        # C1 sink fix: pageImage must run p.image through esc(), so even a
        # malicious value already in book.json can't break out of <img src>.
        template = (helpers.ROOT / "assets" / "viewer.template.html").read_text(
            encoding="utf-8")
        self.assertIn("esc(p.image)", template)
        self.assertNotIn("' + p.image + '", template)  # raw concat is gone

    def test_title_xss_is_escaped(self):
        # I3: title.zh must not be able to break out of <title>.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            data = helpers.read_book(d)
            data["title"]["zh"] = "</title><script>alert(1)</script>"
            helpers.write_book(d, data)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertNotIn("</title><script>", html)
            self.assertIn("&lt;/title&gt;", html)

    def test_title_with_book_json_placeholder_not_clobbered(self):
        # I3: single-pass replace — a title literally equal to __BOOK_JSON__
        # must stay in <title>, not pull the whole book JSON into it.
        with helpers.tmp() as td:
            d = helpers.make_book(td, phase="delivered", with_images=True)
            data = helpers.read_book(d)
            data["title"]["zh"] = "__BOOK_JSON__"
            helpers.write_book(d, data)
            code, out, _ = helpers.run_cli("export", "--dir", d)
            self.assertEqual(code, 0)
            html = Path(out["html"]).read_text(encoding="utf-8")
            self.assertIn("<title>__BOOK_JSON__</title>", html)
