"""Check paired publication, internal navigation, and failed-build preservation."""

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
from pypdf import PdfReader


SOURCE = Path(__file__).resolve().parents[1]


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='whatsapp-publication-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.existing = {}
        pages = ['index.html', 'full-guide/index.html']
        pages += [f'{folder}{theme}/index.html' for folder in ('', 'quick-reference/') for theme in ('light', 'dark')]
        for relative in pages:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / relative, destination)
            if relative.endswith(('light/index.html', 'dark/index.html')):
                link = html.parse(str(destination)).getroot().get_element_by_id('pdf-download').get('href')
                pdf = (destination.parent / unquote(link)).resolve()
                pdf.parent.mkdir(parents=True, exist_ok=True)
                self.existing[pdf] = b'Existing publication: ' + relative.encode()
                pdf.write_bytes(self.existing[pdf])
        spec = importlib.util.spec_from_file_location('whatsapp_builder', SOURCE / 'scripts/build_pdfs.py')
        self.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.builder)
        self.builder.ROOT = self.root

    def run_build(self):
        with patch.object(sys, 'argv', ['build_pdfs.py']), redirect_stdout(io.StringIO()):
            self.builder.main()

    def assert_publication_unchanged(self):
        self.assertEqual(len(self.existing), 4)
        for path, content in self.existing.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertFalse(list(self.root.rglob('*.tmp')))

    def test_both_reading_views_have_matching_theme_pages_and_internal_response_links(self):
        self.run_build()
        counts = []
        for path in self.existing:
            reader = PdfReader(path)
            counts.append(len(reader.pages))
            self.assertIn('v1.0.0' if '-quick-reference-' in path.name else 'v1.0.1', reader.metadata.title)
            self.assertIn('Quick Reference' if '-quick-reference-' in path.name else 'Comprehensive Guide', reader.metadata.title)
            links = [annotation.get_object() for page in reader.pages for annotation in page.get('/Annots', [])]
            destinations = [link['/Dest'] for link in links if '/Dest' in link]
            # A link wrapping across two lines has two clickable rectangles.
            targets = {(destination[0].idnum, tuple(str(value) for value in destination[1:]))
                       for destination in destinations}
            self.assertEqual(len(targets), 4)
            for destination in destinations:
                self.assertIn(destination[0], [page.indirect_reference for page in reader.pages])
        self.assertEqual(counts[0], counts[1])
        self.assertEqual(counts[2], counts[3])

    def test_failure_in_last_render_preserves_all_four_existing_editions(self):
        render = self.builder.write_pdf

        def fail_dark(path, document, theme, edition):
            if theme == 'dark' and document.get_element_by_id('guide').get('data-reading-view') == 'quick':
                raise RuntimeError('Simulated dark-edition failure')
            render(path, document, theme, edition)

        with patch.object(self.builder, 'write_pdf', fail_dark):
            with self.assertRaisesRegex(RuntimeError, 'dark-edition failure'):
                self.run_build()
        self.assert_publication_unchanged()

    def test_oversized_settings_table_preserves_both_existing_editions(self):
        path = self.root / 'index.html'
        document = html.parse(str(path)).getroot()
        document.get_element_by_id('entry-settings').find('.//td').text = 'Oversized table content. ' * 2000
        path.write_bytes(html.tostring(document, encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, 'Revise the layout explicitly'):
            self.run_build()
        self.assert_publication_unchanged()

    def test_invalid_forwarding_destination_preserves_both_existing_editions(self):
        path = self.root / 'dark/index.html'
        document = html.parse(str(path)).getroot()
        document.get_element_by_id('pdf-download').set('href', '../pdfs/wrong-edition.pdf')
        path.write_bytes(html.tostring(document, encoding='utf-8'))
        with self.assertRaisesRegex(ValueError, 'forwarding link must target'):
            self.run_build()
        self.assert_publication_unchanged()


if __name__ == '__main__':
    unittest.main()
