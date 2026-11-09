"""Verify that failed builds preserve the complete existing PDF publication."""

from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from lxml import html


SOURCE = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="openhearted-publication-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        pages = ["index.html", "full-guide/index.html"]
        pages += [f"{folder}{theme}/index.html" for folder in ("", "quick-reference/") for theme in ("light", "dark")]
        self.existing = {}
        for relative in pages:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
            if relative.endswith(("light/index.html", "dark/index.html")):
                link = html.parse(str(destination)).getroot().get_element_by_id("pdf-download").get("href")
                pdf = (destination.parent / unquote(link)).resolve()
                pdf.parent.mkdir(parents=True, exist_ok=True)
                self.existing[pdf] = b"Existing publication: " + relative.encode()
                pdf.write_bytes(self.existing[pdf])
        spec = importlib.util.spec_from_file_location("publication_builder", SOURCE / "scripts/build_pdfs.py")
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        self.builder.ROOT = self.root

    def assert_publication_unchanged(self):
        self.assertEqual(len(self.existing), 4)
        for path, content in self.existing.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(list(self.root.rglob("*.tmp")))

    def test_quick_reference_overflow_preserves_both_document_pairs(self):
        path = self.root / "index.html"
        document = html.parse(str(path)).getroot()
        paragraph = html.Element("p")
        paragraph.text = "Overflow must stop publication. " * 1000
        document.get_element_by_id("introduction").append(paragraph)
        path.write_bytes(html.tostring(document, encoding="utf-8"))
        with patch.object(sys, "argv", ["build_pdfs.py"]), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "Revise the layout explicitly"):
                self.builder.main()
        self.assert_publication_unchanged()

    def test_invalid_destination_preserves_both_document_pairs(self):
        path = self.root / "quick-reference/light/index.html"
        document = html.parse(str(path)).getroot()
        document.get_element_by_id("pdf-download").set("href", "../../pdfs/wrong-edition.pdf")
        path.write_bytes(html.tostring(document, encoding="utf-8"))
        with patch.object(sys, "argv", ["build_pdfs.py"]):
            with self.assertRaisesRegex(ValueError, "forwarding link must target"):
                self.builder.main()
        self.assert_publication_unchanged()


if __name__ == "__main__":
    unittest.main()
