#!/usr/bin/env python3
"""Build both WhatsApp reading views as light and dark PDFs from public HTML.

Run from this resource's directory with: python3 scripts/build_pdfs.py.
Dependencies: reportlab and lxml; fonts default to macOS Arial and Georgia.
"""

import argparse
from copy import deepcopy
from html import escape
from pathlib import Path
import sys

from lxml import html
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from pdf_common import (BOTTOM, CONTENT_WIDTH, HEIGHT, MARGIN, PALETTES, inline as html_inline,
                        measure, pdf_destination, plain, publish_pdf_set,
                        register_fonts, styles_for, write_stories)


ROOT = Path(__file__).resolve().parents[1]


def inline(element):
    return html_inline(element, internal_links=True)


def settings_table(element, styles):
    rows = element.xpath('./thead/tr | ./tbody/tr')
    if not rows:
        raise ValueError('Settings tables require a header and content rows.')
    columns = len(rows[0])
    if columns not in (2, 3) or any(len(row) != columns or any(cell.tag not in ('th', 'td') for cell in row) for row in rows):
        raise ValueError('Settings tables require consistently two or three columns.')
    data = [[Paragraph(inline(cell), styles['table-heading' if cell.tag == 'th' else 'table-cell'])
             for cell in row] for row in rows]
    widths = [CONTENT_WIDTH * .65, CONTENT_WIDTH * .35] if columns == 2 else [142, 115, CONTENT_WIDTH - 257]
    return Table(data, colWidths=widths, style=styles['table-rules'],
                 hAlign='LEFT', spaceBefore=8, spaceAfter=12)


def list_blocks(element, styles, depth=0):
    for item in element:
        if item.tag != 'li':
            raise ValueError('Lists must contain list items.')
        line = html.Element('p')
        line.text = item.text
        for child in item:
            if child.tag != 'ul':
                line.append(deepcopy(child))
        style = ParagraphStyle(f'list-{depth}', parent=styles['body'],
                               leftIndent=14 * (depth + 1), bulletIndent=14 * depth)
        yield Paragraph(inline(line), style, bulletText='•'), False
        for child in item:
            if child.tag == 'ul':
                yield from list_blocks(child, styles, depth + 1)


def content_blocks(element, styles, palette):
    if 'data-pdf-skip' in element.attrib:
        return
    if element.tag == 'div' and 'settings-scroll' in element.classes:
        yield settings_table(element.find('table'), styles), False
    elif element.tag == 'ul':
        yield from list_blocks(element, styles)
    elif 'surge-response' in element.classes:
        style = ParagraphStyle('surge-response', parent=styles['body'], fontSize=13.5,
                               leading=18, spaceAfter=0)
        rules = [('BACKGROUND', (0, 0), (-1, -1), colors.HexColor(palette['tint'])),
                 ('BOX', (0, 0), (-1, -1), 1, colors.HexColor(palette['accent'])),
                 ('LEFTPADDING', (0, 0), (-1, -1), 12),
                 ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                 ('TOPPADDING', (0, 0), (-1, -1), 12),
                 ('BOTTOMPADDING', (0, 0), (-1, -1), 12)]
        yield Table([[Paragraph(inline(element), style)]], colWidths=[CONTENT_WIDTH],
                    style=TableStyle(rules), spaceBefore=10, spaceAfter=12), False
    elif element.tag in ('h2', 'h3'):
        style = styles['section' if element.tag == 'h2' else 'subheading']
        anchors = [element.get('id')] if element.get('id') else []
        section = element.getparent()
        if section.tag == 'section':
            first_heading = section.find('h2') if section.find('h2') is not None else section.find('h3')
            if element is first_heading:
                anchors.append(section.get('id'))
        names = ''.join(f'<a name="{escape(name, quote=True)}"/>' for name in anchors)
        yield Paragraph(names + inline(element), style), True
    elif element.tag == 'p':
        yield Paragraph(inline(element), styles['body']), plain(element).endswith(':')
    elif element.tag == 'hr':
        yield styles['conclusion-divider'], True
    else:
        raise ValueError(f'Unsupported admin guide block: {element.tag}')


def make_stories(document, styles, palette):
    title = plain(document.get_element_by_id('guide-title'))
    opening = [Paragraph(escape(title), styles['title']),
               Paragraph(escape(plain(document.get_element_by_id('guide-subtitle'))), styles['subtitle']),
               Paragraph(inline(document.find_class('tagline')[0]), styles['summary'])]
    pages = [opening]
    available = HEIGHT - MARGIN - BOTTOM
    for section in document.get_element_by_id('guide'):
        if section.tag == 'nav':
            continue
        if section.tag != 'section':
            raise ValueError('The admin guide must contain sections and navigation.')
        heading = section.find('h2') if section.find('h2') is not None else section.find('h3')
        if heading is None:
            raise ValueError('Every admin guide section requires a heading.')
        units, pending = [], []
        elements = [element for element in section if 'data-pdf-skip' not in element.attrib]
        for position, element in enumerate(elements):
            next_table = position + 1 < len(elements) and 'settings-scroll' in elements[position + 1].classes
            for block, keep_next in content_blocks(element, styles, palette):
                pending.append(block)
                keep_next = keep_next or (element.tag == 'p' and next_table)
                if not keep_next:
                    units.append(pending)
                    pending = []
        if pending:
            units.append(pending)
        for index, unit in enumerate(units):
            if measure(pages[-1] + unit) > available:
                page = [Paragraph(escape(title.upper()), styles['kicker'])]
                if index:
                    page.append(Paragraph(escape(plain(heading)) + ' (continued)', styles['principle']))
                pages.append(page)
            pages[-1].extend(unit)
    return pages


def write_pdf(path, document, theme, edition):
    palette = PALETTES[theme]
    stories = make_stories(document, styles_for(palette), palette)
    kind = document.get_element_by_id('guide').get('data-reading-view')
    labels = {'quick': 'Quick Reference', 'comprehensive': 'Comprehensive Guide'}
    if kind not in labels:
        raise ValueError('The guide must declare its quick or comprehensive reading view.')
    write_stories(path, stories, title=plain(document.get_element_by_id('guide-title')),
                  subtitle=plain(document.get_element_by_id('guide-subtitle')),
                  label=labels[kind], edition=edition, theme=theme,
                  author='Independent resource', keywords='WhatsApp, group admins, scam prevention, recovery')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-dir', type=Path, default=Path('/System/Library/Fonts/Supplemental'))
    args = parser.parse_args()
    register_fonts(args.font_dir)
    publications = []
    for source, routes, prefix in (
        (ROOT / 'full-guide/index.html', ROOT, 'whatsapp-spam-dojo'),
        (ROOT / 'index.html', ROOT / 'quick-reference', 'whatsapp-spam-dojo-quick-reference'),
    ):
        document = html.parse(str(source)).getroot()
        edition = document.find('.//time').get('datetime') + '-' + plain(document.get_element_by_id('revision'))
        for theme in PALETTES:
            expected = ROOT / 'pdfs' / f'{prefix}-{edition}-{theme}.pdf'
            destination = pdf_destination(routes / theme / 'index.html', expected)
            publications.append((document, theme, edition, destination))
    publish_pdf_set(publications, write_pdf)


if __name__ == '__main__':
    main()
