#!/usr/bin/env python3
"""Build the admin PDFs from public HTML with embedded 12-point body text.

Run: python3 scripts/build_pdfs.py
Dependencies: reportlab and lxml; fonts default to macOS Arial and Georgia.
The admin HTML owns the settings and practice copy. Download pages own versioned
destinations. Routine role checks and active host recovery stay in the quick
reference, alongside the response they support.
"""

import argparse
from html import escape
from pathlib import Path
import sys

from lxml import html
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, Paragraph, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1] / 'scripts'))
from pdf_common import (CONTENT_WIDTH, inline, pdf_destination, plain, publish_pdf_set, register_fonts,
                        styles_for, write_stories)

PALETTES = {
    'light': {'background': '#FFFFFF', 'text': '#24211D', 'muted': '#615B52',
              'accent': '#6B4F2A', 'border': '#DED8CE', 'tint': '#F0ECE4'},
    'dark': {'background': '#171513', 'text': '#F4EFE7', 'muted': '#C7BFB3',
             'accent': '#E0BD86', 'border': '#51493E', 'tint': '#2C2721'},
}


def list_blocks(element, styles, *, depth=0):
    blocks = []
    ordered = element.tag == 'ol'
    for index, item in enumerate(element):
        if item.tag != 'li':
            raise ValueError('A checklist must contain only list items.')
        if len(item.xpath('./ul | ./ol')):
            raise ValueError('Nested checklists need an explicit layout.')
        marker = f'{chr(97 + index)}.' if ordered else '•'
        style = ParagraphStyle(f'list-{depth}', parent=styles['body'],
                               leftIndent=14 * (depth + 1), bulletIndent=14 * depth,
                               bulletFontName='Body', bulletFontSize=12, spaceAfter=5)
        blocks.append(Paragraph(inline(item), style, bulletText=marker))
    return blocks


def blocks_for(element, styles):
    if element.tag in ('h2', 'h3'):
        return [Paragraph(inline(element), styles['section' if element.tag == 'h2' else 'subheading'])]
    if element.tag == 'p':
        return [Paragraph(inline(element), styles['body'])]
    if element.tag in ('ul', 'ol'):
        return list_blocks(element, styles)
    raise ValueError(f'Unsupported admin block: {element.tag}')


def setting_unit(section, styles):
    heading = section.find('h3')
    risk = next((child for child in section if child.tag == 'p' and 'setting-risk' in child.classes), None)
    title = inline(heading)
    if risk is not None:
        title += ' — <font name="Body-Italic">' + inline(risk) + '</font>'
    blocks = [Paragraph(title, styles['setting'])]
    for element in section:
        if element is heading or element is risk or element.tag == 'details':
            continue
        blocks.extend(blocks_for(element, styles))
    screenshot = section.xpath('./details//img')
    if section.get('id') not in ('chat', 'timers') or not screenshot:
        return blocks
    image_node = screenshot[0]
    image_width = 125 if section.get('id') == 'chat' else 110
    ratio = float(image_node.get('height')) / float(image_node.get('width'))
    picture = Image(str((ROOT / image_node.get('src')).resolve()),
                    width=image_width, height=image_width * ratio)
    # Keep text and its screenshot in separate columns; neither can cover the other.
    return [Table([[blocks, picture]], colWidths=[CONTENT_WIDTH - image_width - 16, image_width + 16],
                  style=TableStyle([
                      ('FONTNAME', (0, 0), (-1, -1), 'Body'),
                      ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                      ('LEFTPADDING', (0, 0), (0, 0), 0),
                      ('RIGHTPADDING', (0, 0), (0, 0), 0),
                      ('LEFTPADDING', (1, 0), (1, 0), 16),
                      ('RIGHTPADDING', (1, 0), (1, 0), 0),
                      ('TOPPADDING', (0, 0), (-1, -1), 0),
                      ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                  ]), spaceBefore=4, spaceAfter=5)]


def make_stories(document, palette):
    styles = styles_for(palette)
    styles['title'].fontSize = 27
    styles['title'].leading = 31
    styles['section'].spaceBefore = 8
    styles['section'].spaceAfter = 7
    styles['setting'] = ParagraphStyle('setting', parent=styles['body'], fontName='Body-Bold',
                                      spaceBefore=6, spaceAfter=4)
    pages = [[Paragraph('SERENITY STRATEGY FOR ZOOM TROLLS', styles['kicker']),
              Paragraph(escape(plain(document.get_element_by_id('guide-title')).replace('*', '').strip()) + '*', styles['title']),
              Paragraph(inline(document.get_element_by_id('guide-subtitle')), styles['subtitle'])]]
    settings = document.get_element_by_id('settings')
    opening = [Paragraph(inline(settings.find('h2')), styles['section']),
               Paragraph(inline(document.get_element_by_id('settings-intro')), styles['body'])]
    for index, setting in enumerate(settings.xpath('./section')):
        if setting.get('id') == 'timers':
            pages.append([Paragraph('ADMIN PREPARATION · SERENITY STRATEGY FOR ZOOM TROLLS', styles['kicker']),
                          Paragraph('Meeting settings (continued)', styles['section'])])
        pages[-1].extend((opening if index == 0 else []) + setting_unit(setting, styles))
    practice = document.get_element_by_id('practice')
    for index, topic in enumerate(practice.xpath('./section')):
        unit = [Paragraph(inline(practice.find('h2')), styles['section'])] if index == 0 else []
        unit.extend(block for element in topic if element.tag != 'details'
                    for block in blocks_for(element, styles))
        pages[-1].extend(unit)
    pages[-1].extend([Paragraph(inline(document.get_element_by_id('response-link')), styles['body']),
                      Paragraph('*' + escape(plain(document.get_element_by_id('concept-five-text'))), styles['note'])])
    return pages


def write_pdf(path, document, theme, edition):
    palette = PALETTES[theme]
    stories = make_stories(document, palette)
    write_stories(path, stories, title='Serenity Strategy for Zoom Trolls',
                  subtitle=plain(document.get_element_by_id('guide-subtitle')),
                  label='Admin Preparation', edition=edition, theme=theme,
                  author='Independent resource', keywords='Zoom, meeting admins, host tools, preparation, recovery')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=Path('/System/Library/Fonts/Supplemental'))
    args = parser.parse_args()
    register_fonts(args.font_dir)
    document = html.parse(str(ROOT / 'index.html')).getroot()
    edition = document.find('.//time').get('datetime') + '-' + plain(document.get_element_by_id('revision'))
    publications = []
    for theme in PALETTES:
        suffix = ' | Dark' if theme == 'dark' else ''
        expected = ROOT / 'pdfs' / f'Serenity Strategy for Zoom Trolls | Admin Preparation | {edition}{suffix}.pdf'
        destination = pdf_destination(ROOT / theme / 'index.html', expected)
        publications.append((document, theme, edition, destination))
    publish_pdf_set(publications, write_pdf)


if __name__ == '__main__':
    main()
