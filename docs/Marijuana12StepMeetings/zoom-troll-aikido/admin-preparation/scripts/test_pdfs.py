"""Check the published response/preparation split and faithful PDF content."""

from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

from lxml import html
import pdfplumber
from pypdf import PdfReader
from pypdf.generic import ContentStream


ROOT = Path(__file__).resolve().parents[1]
QUICK = ROOT.parent


def normalise(text):
    return ' '.join(text.split())


def download_path(root, theme):
    path = root / theme / 'index.html'
    document = html.parse(str(path)).getroot()
    link = urlsplit(document.get_element_by_id('pdf-download').get('href'))
    if link.scheme or link.netloc or link.query or link.fragment:
        raise ValueError('The forwarding destination must be a local PDF.')
    return (path.parent / unquote(link.path)).resolve()


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = html.parse(str(ROOT / 'index.html')).getroot()
        cls.quick = html.parse(str(QUICK / 'index.html')).getroot()
        cls.version = normalise(cls.admin.get_element_by_id('revision').text_content())
        cls.canonical = cls.admin.xpath('//link[@rel="canonical"]/@href')[0]

    def test_downloads_open_distinct_current_resources(self):
        for root, count in ((QUICK, 1), (ROOT, 2)):
            for theme in ('light', 'dark'):
                with self.subTest(resource=root.name, theme=theme):
                    path = download_path(root, theme)
                    self.assertTrue(path.is_file(), path)
                    self.assertIn(self.version, path.name)
                    reader = PdfReader(path)
                    self.assertEqual(len(reader.pages), count)
                    self.assertIn(self.version, reader.metadata.title)
                    with pdfplumber.open(path) as document:
                        for page in document.pages:
                            # Word grouping can insert spaces into native monospaced
                            # footers. Check the actual painted characters directly.
                            self.assertIn(self.version, ''.join(char['text'] for char in page.chars))
        expected = {download_path(ROOT, theme) for theme in ('light', 'dark')}
        self.assertEqual({p.resolve() for p in (ROOT / 'pdfs').glob('*.pdf')}, expected)

    def test_admin_pdfs_preserve_every_settings_and_practice_block(self):
        blocks = [normalise(node.text_content()) for node in self.admin.xpath(
            '//main//h2 | //main//h3 | //main//p | //main//li')]
        for theme in ('light', 'dark'):
            reader = PdfReader(download_path(ROOT, theme))
            text = normalise(' '.join(page.extract_text() for page in reader.pages))
            with self.subTest(theme=theme):
                for block in blocks:
                    self.assertIn(block, text)
                for absent in ('Verify co-host identities', 'Reclaim host', 'Revoke co-host',
                               'Host tools vary:',
                               'Participants may still be able to use these features.'):
                    self.assertNotIn(absent, text)
                self.assertTrue(any(
                    annotation.get_object().get('/A', {}).get('/URI', '').endswith('/index.html#response')
                    for page in reader.pages for annotation in page.get('/Annots', [])))

    def test_admin_fonts_are_embedded_for_portable_rendering(self):
        for theme in ('light', 'dark'):
            reader = PdfReader(download_path(ROOT, theme))
            for page in reader.pages:
                for font in page['/Resources']['/Font'].values():
                    descriptor = font.get_object().get('/FontDescriptor')
                    self.assertIsNotNone(descriptor)
                    descriptor = descriptor.get_object()
                    self.assertTrue(any(key in descriptor for key in ('/FontFile', '/FontFile2', '/FontFile3')))

    def test_role_checks_stay_on_quick_web_and_cohost_guidance_reaches_print(self):
        for identifier in ('meeting-preparation', 'secure-roles', 'control-availability'):
            self.assertIsNotNone(self.quick.get_element_by_id(identifier))
            self.assertFalse(self.admin.xpath(f'//*[@id="{identifier}"]'))
        self.assertTrue(self.quick.xpath('//*[@id="meeting-preparation"]//*[@id="control-availability"]'))
        practice = self.admin.get_element_by_id('practice')
        self.assertEqual([normalise(h.text_content()) for h in practice.xpath('.//h3')], ['Make it fun!'])
        self.assertTrue(self.admin.xpath('//*[@id="settings"]//*[@id="account-settings"]'))
        for theme in ('light', 'dark'):
            reader = PdfReader(download_path(QUICK, theme))
            with pdfplumber.open(download_path(QUICK, theme)) as document:
                text = normalise(document.pages[0].extract_text())
            self.assertIn(normalise(self.quick.get_element_by_id('cohost-host-tools').text_content()), text)
            self.assertNotIn('1/2', text)
            self.assertNotIn('Admin preparation', text)
            self.assertFalse(any(annotation.get_object().get('/A', {}).get('/URI') == self.canonical
                                 for annotation in reader.pages[0].get('/Annots', [])))

    def test_quick_announcements_match_their_tagged_print_copy(self):
        source = [normalise(node.text_content()) for node in (
            self.quick.get_element_by_id('continue').xpath('.//blockquote/p')[0],
            self.quick.get_element_by_id('protect-yourself').find('p'),
            self.quick.get_element_by_id('member-reminder').xpath('.//p[@class="announcement-note"]')[0],
        )]
        for theme in ('light', 'dark'):
            reader = PdfReader(download_path(QUICK, theme))
            operations = ContentStream(reader.pages[0]['/Contents'], reader).operations
            tagged_copy = [normalise(args[1]['/ActualText']) for args, operator in operations
                           if operator == b'BDC' and len(args) > 1
                           and isinstance(args[1], dict) and '/ActualText' in args[1]]
            with self.subTest(theme=theme):
                for paragraph in source:
                    self.assertIn(paragraph, tagged_copy)

    def test_printed_cohost_controls_keep_color_emphasis_and_underlines(self):
        warning = normalise(self.quick.get_element_by_id('cohost-host-tools').text_content())
        for theme in ('light', 'dark'):
            path = download_path(QUICK, theme)
            reader = PdfReader(path)
            operations = ContentStream(reader.pages[0]['/Contents'], reader).operations
            identifier = next(int(args[1]['/MCID']) for args, operator in operations
                              if operator == b'BDC' and len(args) > 1 and isinstance(args[1], dict)
                              and normalise(args[1].get('/ActualText', '')) == warning)
            with pdfplumber.open(path) as document:
                page = document.pages[0]
                chars = [char for char in page.chars if char.get('mcid') == identifier]
                text = ''.join(char['text'] for char in chars)
                for command, dominant_channel in (('Suspend', 0), ('Turn all off', 2)):
                    with self.subTest(theme=theme, command=command):
                        start = text.index(command)
                        selected = chars[start:start + len(command)]
                        color = selected[0]['non_stroking_color']
                        self.assertTrue(all(char['non_stroking_color'] == color for char in selected))
                        self.assertGreater(color[dominant_channel], color[2 - dominant_channel])
                        self.assertTrue(any('Bold' in char['fontname'] for char in selected))
                        left = min(char['x0'] for char in selected)
                        right = max(char['x1'] for char in selected)
                        self.assertTrue(any(
                            abs(line['x0'] - left) < .1 and abs(line['x1'] - right) < .1
                            and line['stroking_color'] == color
                            and selected[0]['top'] < line['top'] < selected[0]['bottom'] + 2
                            for line in page.lines if line.get('mcid') == identifier))


if __name__ == '__main__':
    unittest.main()
