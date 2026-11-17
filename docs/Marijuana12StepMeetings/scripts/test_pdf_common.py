"""Check latest-only publication and preservation on failed builds."""

from contextlib import redirect_stdout
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pdf_common import prune_superseded_pdfs, publish_pdf_set


class RetentionTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="pdf-retention-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.current = []
        self.old = []
        self.publications = []
        for family, edition in (("guide", "2026-11-16-v1.1.0"),
                                ("guide-quick-reference", "2026-11-09-v1.0.0")):
            for theme in ("light", "dark"):
                current = self.write(f"{family}-{edition}-{theme}.pdf", b"current")
                old = self.write(f"{family}-2026-11-01-v1-{theme}.pdf", b"old")
                self.current.append(current)
                self.old.append(old)
                self.publications.append((family, theme, edition, current))
        self.unrelated = [self.write("meeting-notes.pdf", b"notes"),
                          self.write("other-guide-2026-11-01-v1.0.0-light.pdf", b"other")]

    def write(self, name, content):
        path = self.root/name
        path.write_bytes(content)
        return path

    @staticmethod
    def render(path, document, theme, edition):
        path.write_bytes(b"replacement")

    def test_success_retires_old_editions_but_preserves_unrelated_pdfs(self):
        with redirect_stdout(io.StringIO()):
            publish_pdf_set(self.publications, self.render)
        self.assertEqual(set(self.root.glob("*.pdf")), set(self.current+self.unrelated))
        for path in self.current:
            self.assertEqual(path.read_bytes(), b"replacement")
        self.assertEqual(self.unrelated[0].read_bytes(), b"notes")
        self.assertEqual(self.unrelated[1].read_bytes(), b"other")

    def test_one_reading_view_does_not_retire_the_other(self):
        with redirect_stdout(io.StringIO()):
            prune_superseded_pdfs(self.current[:2])
        self.assertTrue(all(not path.exists() for path in self.old[:2]))
        self.assertTrue(all(path.exists() for path in self.old[2:]+self.current))

    def test_failed_last_render_preserves_current_and_old_editions(self):
        def render(path, document, theme, edition):
            if document == "guide-quick-reference" and theme == "dark":
                raise RuntimeError("Last render failed")
            self.render(path, document, theme, edition)
        with self.assertRaisesRegex(RuntimeError, "Last render failed"):
            publish_pdf_set(self.publications, render)
        for path in self.current:
            self.assertEqual(path.read_bytes(), b"current")
        for path in self.old:
            self.assertEqual(path.read_bytes(), b"old")

    def test_failed_publication_keeps_all_old_editions(self):
        import pdf_common
        replace = pdf_common.os.replace

        def fail_last(source, destination):
            if destination == self.current[-1]:
                raise OSError("Last publication failed")
            replace(source, destination)

        with patch("pdf_common.os.replace", fail_last), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, "Last publication failed"):
                publish_pdf_set(self.publications, self.render)
        self.assertTrue(all(path.is_file() for path in self.current))
        self.assertTrue(all(path.read_bytes() == b"old" for path in self.old))
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_missing_replacement_stops_cleanup(self):
        self.current[-1].unlink()
        with self.assertRaisesRegex(FileNotFoundError, "Current PDF is not ready"):
            prune_superseded_pdfs(self.current)
        self.assertTrue(all(path.exists() for path in self.old))

    def test_unknown_filename_stops_cleanup(self):
        unknown = self.write("current.pdf", b"unknown")
        with self.assertRaisesRegex(ValueError, "Unrecognized versioned PDF filename"):
            prune_superseded_pdfs([*self.current, unknown])
        self.assertTrue(all(path.exists() for path in self.old))

    def test_native_zoom_editions_use_the_same_retention_policy(self):
        prefix = "Serenity Strategy for Zoom Trolls | Quick Reference | "
        current = [self.write(f"{prefix}2026-11-16-v4.10.0{suffix}.pdf", b"zoom")
                   for suffix in ("", " | Dark")]
        old = [self.write(f"{prefix}{edition}{suffix}.pdf", b"old zoom")
               for edition in ("2026-10-22-E2", "2026-11-12-v4.8.2")
               for suffix in ("", " | Dark")]
        with redirect_stdout(io.StringIO()):
            removed = prune_superseded_pdfs(current)
        self.assertEqual(set(removed), set(old))
        self.assertTrue(all(path.read_bytes() == b"zoom" for path in current))
        self.assertTrue(all(path.exists() for path in self.current+self.old+self.unrelated))


if __name__ == "__main__":
    unittest.main()
