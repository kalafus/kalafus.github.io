#!/usr/bin/env python3
"""Build the light and dark PDFs from the public HTML's authoritative wording.

Dependencies: reportlab, lxml. The default embedded fonts are macOS Arial and
Georgia; --font-dir may point to another licensed copy of those same font files.
"""

import argparse
from html import escape
from pathlib import Path
import sys

from lxml import html
from reportlab.platypus import Paragraph, Table

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from pdf_common import (CONTENT_WIDTH, HEIGHT, PALETTES, inline, plain, register_fonts,
                        styles_for, pdf_destination, publish_pdf_set, write_stories)


ROOT = Path(__file__).resolve().parents[1]


def dialectics_table(element, styles):
    table = element.find("table")
    rows = table.xpath("./thead/tr | ./tbody/tr")
    data = []
    for row in rows:
        cells = list(row)
        if len(cells) != 3 or any(cell.tag not in ("th", "td") for cell in cells):
            raise ValueError("The dialectics table requires three cells in every row.")
        data.append([Paragraph(inline(cell), styles["table-heading" if cell.tag == "th" else "table-cell"])
                     for cell in cells])
    if len(data) != 5:
        raise ValueError("The dialectics table requires a header and four lenses.")
    lens_width = 70
    return Table(data, colWidths=[lens_width, (CONTENT_WIDTH - lens_width) / 2, (CONTENT_WIDTH - lens_width) / 2],
                 style=styles["table-rules"], hAlign="LEFT", spaceBefore=8, spaceAfter=12)


def content_block(element, styles):
    """Render every supported content block, rejecting unhandled structure."""
    if element.tag == "blockquote" and "shared-note" in element.classes:
        if len(element) != 1 or element[0].tag != "p":
            raise ValueError("The shared-playbook note must contain one paragraph.")
        return content_block(element[0], styles)
    if element.tag == "hr" and "conclusion-divider" in element.classes:
        return styles["conclusion-divider"]
    if element.tag == "div" and "data-dialectics" in element.attrib:
        return dialectics_table(element, styles)
    if element.tag in ("h2", "h3", "h4"):
        kind = {"h2": "section", "h3": "principle", "h4": "subheading"}[element.tag]
        if element.tag == "h2" and "conclusion-card" in element.getparent().classes:
            kind = "conclusion-section"
        return Paragraph(escape(plain(element)), styles[kind])
    if element.tag != "p":
        raise ValueError(f"Unsupported content block: {element.tag}")
    if "closing" in element.classes:
        return Paragraph(escape(plain(element)), styles["closing"])
    kind = "quote" if "pull-quote" in element.classes else "body"
    if element.get("id") == "independent-note":
        kind = "note"
    return Paragraph(inline(element), styles[kind])


def opening(document, styles):
    title = plain(document.get_element_by_id("document-title"))
    first = [Paragraph(escape(title), styles["title"])]
    kind = document.xpath('//*[@id="document-kind"]')
    if kind:
        first.append(Paragraph(escape(plain(kind[0])), styles["subheading"]))
    first.append(Paragraph(escape(plain(document.get_element_by_id("document-subtitle"))), styles["subtitle"]))
    first += [content_block(element, styles) for element in document.get_element_by_id("introduction")]
    return first


def append_closing_sections(document, pages, styles, section_ids):
    """Keep shared cards and explicit closing-page breaks consistent in both views."""
    title = plain(document.get_element_by_id("document-title"))

    def start_page():
        pages.append([Paragraph(escape(title.upper()), styles["kicker"])])

    for section_id in section_ids:
        section = document.get_element_by_id(section_id)
        if "data-pdf-break-before" in section.attrib:
            start_page()
        for element in section:
            if "data-pdf-skip" in element.attrib:
                continue
            if "data-pdf-break-before" in element.attrib:
                start_page()
            if element.tag == "section" and "conclusion-card" in element.classes:
                pages[-1] += [content_block(child, styles) for child in element if "data-pdf-skip" not in child.attrib]
            else:
                pages[-1].append(content_block(element, styles))
    pages[-1].append(content_block(document.get_element_by_id("independent-note"), styles))


def make_stories(document, styles):
    title = plain(document.get_element_by_id("document-title"))
    first = opening(document, styles)
    first.append(Paragraph(escape(plain(document.get_element_by_id("principles-heading"))), styles["section"]))
    principles = document.find_class("principle")
    for principle in principles:
        summary = principle.find("summary")
        marker = escape(plain(summary.find_class("principle-marker")[0]))
        copy = summary.find_class("summary-copy")[0]
        label = escape(plain(copy.find("strong")))
        text = escape(plain(copy.find("span")))
        first.append(Paragraph(f"<b>{marker} {label}</b> {text}", styles["summary"]))
    first += [content_block(note, styles) for note in document.find_class("principles-note")]

    pages = [first]

    def start_page(continued_heading=None):
        page = [Paragraph(escape(title.upper()), styles["kicker"])]
        if continued_heading is not None:
            page.append(Paragraph(escape(plain(continued_heading)) + " (continued)", styles["principle"]))
        pages.append(page)

    # The article owns the page breaks as well as the wording. Long principles
    # can continue at a paragraph or subheading without splitting a block.
    for principle in principles:
        body = principle.find("div")
        heading, *elements = list(body)
        elements = [element for element in elements if "data-pdf-skip" not in element.attrib]
        if heading.tag != "h3":
            raise ValueError(f"{principle.get('id')} must start with its publication heading.")
        if "data-pdf-break-before" in principle.attrib:
            start_page()
        pages[-1].append(content_block(heading, styles))
        for index, element in enumerate(elements):
            if "data-pdf-break-before" in element.attrib:
                if index == 0:
                    raise ValueError("Move a break before the first paragraph onto its principle.")
                start_page(heading)
            pages[-1].append(content_block(element, styles))
    append_closing_sections(document, pages, styles, ("conclusion", "feedback"))
    return pages


def make_quick_stories(document, styles):
    title = plain(document.get_element_by_id("document-title"))
    pages = [opening(document, styles)]
    for principle in document.find_class("quick-principle"):
        heading, *elements = list(principle.find("div"))
        if heading.tag != "h3":
            raise ValueError("A quick-reference principle must begin with its heading.")
        if "data-pdf-break-before" in principle.attrib:
            pages.append([Paragraph(escape(title.upper()), styles["kicker"])])
        pages[-1].append(Paragraph(escape(plain(heading)), styles["principle"]))
        introduction = principle.find("summary").find_class("summary-copy")[0].find("span")
        pages[-1].append(Paragraph(inline(introduction), styles["body"]))
        for element in elements:
            if "data-pdf-skip" in element.attrib:
                continue
            if "data-pdf-break-before" in element.attrib:
                pages.append([Paragraph(escape(title.upper()), styles["kicker"]),
                              Paragraph(escape(plain(heading)) + " (continued)", styles["principle"])])
            pages[-1].append(content_block(element, styles))
    append_closing_sections(document, pages, styles, ("conclusion",))
    return pages


def write_pdf(path, document, theme, edition):
    styles = styles_for(PALETTES[theme])
    quick = bool(document.find_class("quick-principle"))
    stories = make_quick_stories(document, styles) if quick else make_stories(document, styles)
    write_stories(path, stories,
                  title=plain(document.get_element_by_id("document-title")),
                  subtitle=plain(document.get_element_by_id("document-subtitle")),
                  label="Quick Reference" if quick else "Comprehensive Guide",
                  edition=edition, theme=theme)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font-dir", type=Path, default=Path("/System/Library/Fonts/Supplemental"))
    args = parser.parse_args()
    register_fonts(args.font_dir)
    # Versioned downloads retain their published URLs after the guide's move.
    pdf_directory = ROOT.parent / "openhearted-not-unguarded" / "pdfs"
    publications = []
    for source, routes, prefix in (
        (ROOT / "full-guide/index.html", ROOT, "openhearted-not-unguarded"),
        (ROOT / "index.html", ROOT / "quick-reference", "openhearted-not-unguarded-quick-reference"),
    ):
        document = html.parse(str(source)).getroot()
        date = document.find(".//time").get("datetime")
        revision = plain(document.get_element_by_id("revision"))
        edition = f"{date}-{revision}"
        for theme in PALETTES:
            forwarding_page = routes / theme / "index.html"
            expected = pdf_directory / f"{prefix}-{edition}-{theme}.pdf"
            path = pdf_destination(forwarding_page, expected)
            publications.append((document, theme, edition, path))

    publish_pdf_set(publications, write_pdf)


if __name__ == "__main__":
    main()
