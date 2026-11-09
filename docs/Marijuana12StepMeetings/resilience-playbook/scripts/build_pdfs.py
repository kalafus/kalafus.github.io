#!/usr/bin/env python3
"""Build the light and dark PDFs from the public HTML's authoritative wording.

Dependencies: reportlab, lxml. The default embedded fonts are macOS Arial and
Georgia; --font-dir may point to another licensed copy of those same font files.
"""

import argparse
import os
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urljoin, urlsplit

from lxml import html
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import HRFlowable, Paragraph, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 612, 792  # US Letter, points.
MARGIN = 40
CONTENT_WIDTH = WIDTH - 2 * MARGIN
BOTTOM = 50  # Keeps all text above the running footer.
PALETTES = {
    "light": {"background": "#FFFFFF", "text": "#242B27", "muted": "#59645D", "accent": "#355E4C", "border": "#CCD4C9", "tint": "#EDF0E9"},
    "dark": {"background": "#171C19", "text": "#F0F1E9", "muted": "#B9C5BB", "accent": "#AFCFB7", "border": "#425548", "tint": "#27362D"},
}


def plain(element):
    return " ".join(" ".join(element.itertext()).split())


def inline(element):
    """Translate only the content's supported inline markup to PDF markup."""
    result = escape(element.text or "")
    for child in element:
        content = inline(child)
        if child.tag == "strong":
            result += f"<b>{content}</b>"
        elif child.tag == "em":
            result += f"<i>{content}</i>"
        elif child.tag == "a":
            href = child.get("href")
            if not urlsplit(href).scheme:
                canonical = child.getroottree().xpath('//link[@rel="canonical"]/@href')
                if len(canonical) != 1:
                    raise ValueError("A relative PDF link requires the article's canonical URL.")
                href = urljoin(canonical[0], href)
            href = escape(href, quote=True)
            result += f'<a href="{href}"><u>{content}</u></a>'
        elif child.tag == "br":
            result += "<br/>"
        elif child.get("aria-hidden") == "true":
            pass
        else:
            raise ValueError(f"Unsupported inline element: {child.tag}")
        result += escape(child.tail or "")
    return result


def register_fonts(directory):
    fonts = {
        "Body": "Arial.ttf", "Body-Bold": "Arial Bold.ttf",
        "Body-Italic": "Arial Italic.ttf", "Body-BoldItalic": "Arial Bold Italic.ttf",
        "Display": "Georgia.ttf", "Display-Italic": "Georgia Italic.ttf",
    }
    for name, filename in fonts.items():
        path = directory / filename
        if not path.is_file():
            raise FileNotFoundError(f"Required font missing: {path}")
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")


def styles_for(palette):
    base = ParagraphStyle("body", fontName="Body", fontSize=12, leading=15,
                          textColor=colors.HexColor(palette["text"]), spaceAfter=4,
                          alignment=TA_LEFT, splitLongWords=False)
    section = ParagraphStyle("section", parent=base, fontName="Display", fontSize=14.2,
                             leading=17.2, textColor=colors.HexColor(palette["accent"]),
                             spaceBefore=7, spaceAfter=9)
    return {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontName="Display", fontSize=29,
                                leading=33, spaceAfter=7),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=12.3, leading=16,
                                   textColor=colors.HexColor(palette["muted"]), spaceAfter=18),
        "section": section,
        "conclusion-section": ParagraphStyle("conclusion-section", parent=section, spaceAfter=7),
        "principle": ParagraphStyle("principle", parent=base, fontName="Body-Bold", fontSize=12.5,
                                    leading=16, textColor=colors.HexColor(palette["accent"]),
                                    spaceBefore=8, spaceAfter=5),
        "subheading": ParagraphStyle("subheading", parent=base, fontName="Body-Bold", fontSize=12,
                                     leading=15, textColor=colors.HexColor(palette["accent"]),
                                     spaceBefore=8, spaceAfter=4),
        "table-cell": ParagraphStyle("table-cell", parent=base, spaceAfter=0),
        "table-heading": ParagraphStyle("table-heading", parent=base, fontName="Body-Bold",
                                       textColor=colors.HexColor(palette["accent"]), spaceAfter=0),
        "table-rules": TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(palette["tint"])),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor(palette["tint"])),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor(palette["border"])),
        ]),
        "conclusion-divider": HRFlowable(width=CONTENT_WIDTH, thickness=0.5,
                                         color=colors.HexColor(palette["border"]),
                                         spaceBefore=12, spaceAfter=12),
        "summary": ParagraphStyle("summary", parent=base, spaceAfter=6),
        "quote": ParagraphStyle("quote", parent=base, fontName="Display-Italic", fontSize=13,
                                leading=17, textColor=colors.HexColor(palette["accent"]),
                                spaceBefore=4, spaceAfter=10),
        "closing": ParagraphStyle("closing", parent=base, fontName="Display", fontSize=14.3,
                                  leading=18, textColor=colors.HexColor(palette["accent"]),
                                  spaceBefore=5, spaceAfter=11),
        "note": ParagraphStyle("note", parent=base, fontSize=8.4, leading=11.2,
                               textColor=colors.HexColor(palette["muted"]), spaceBefore=5),
        "kicker": ParagraphStyle("kicker", parent=base, fontSize=8, leading=10.5,
                                 textColor=colors.HexColor(palette["muted"]), spaceAfter=9),
    }


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
    for section_id in ("conclusion", "feedback"):
        section = document.get_element_by_id(section_id)
        if "data-pdf-break-before" in section.attrib:
            start_page()
        for element in section:
            if "data-pdf-break-before" in element.attrib:
                start_page()
            if element.tag == "section" and "conclusion-card" in element.classes:
                pages[-1] += [content_block(child, styles) for child in element]
            else:
                pages[-1].append(content_block(element, styles))
    pages[-1].append(content_block(document.get_element_by_id("independent-note"), styles))
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
    pages[-1] += [content_block(element, styles) for element in document.get_element_by_id("conclusion")]
    pages[-1].append(content_block(document.get_element_by_id("independent-note"), styles))
    return pages


def measure(story):
    # The last block's trailing gap has no content to separate from it. Measure
    # the drawn extent so that empty space after the final line cannot overflow.
    total = sum(item.getSpaceBefore() + item.wrap(CONTENT_WIDTH, HEIGHT)[1] + item.getSpaceAfter() for item in story)
    return total - story[-1].getSpaceAfter()


def write_pdf(path, document, theme, edition):
    palette = PALETTES[theme]
    styles = styles_for(palette)
    quick = bool(document.find_class("quick-principle"))
    stories = make_quick_stories(document, styles) if quick else make_stories(document, styles)
    available = HEIGHT - MARGIN - BOTTOM
    for number, story in enumerate(stories, 1):
        required = measure(story)
        if required > available:
            raise ValueError(f"Page {number} needs {required:.1f}pt; only {available:.1f}pt available. Revise the layout explicitly.")

    pdf = canvas.Canvas(str(path), pagesize=(WIDTH, HEIGHT), pageCompression=1, invariant=1)
    title = plain(document.get_element_by_id("document-title"))
    label = "Quick Reference" if quick else "Comprehensive Guide"
    pdf.setTitle(f"{title} | {label} | {edition} | {theme.title()}")
    pdf.setAuthor("Independent, member-created resource")
    pdf.setSubject(plain(document.get_element_by_id("document-subtitle")))
    pdf.setKeywords("recovery, connection, discernment, autonomy, support")
    for number, story in enumerate(stories, 1):
        pdf.setFillColor(colors.HexColor(palette["background"]))
        pdf.rect(0, 0, WIDTH, HEIGHT, fill=1, stroke=0)
        y = HEIGHT - MARGIN
        for item in story:
            y -= item.getSpaceBefore()
            _, height = item.wrap(CONTENT_WIDTH, HEIGHT)
            item.drawOn(pdf, MARGIN, y - height)
            y -= height + item.getSpaceAfter()
        pdf.setStrokeColor(colors.HexColor(palette["border"]))
        pdf.setLineWidth(0.6)
        pdf.line(MARGIN, 39, WIDTH - MARGIN, 39)
        pdf.setFillColor(colors.HexColor(palette["muted"]))
        pdf.setFont("Body", 7.4)
        pdf.drawString(MARGIN, 25, f"{title}  |  {label}  |  {edition}")
        pdf.drawRightString(WIDTH - MARGIN, 25, f"{number} / {len(stories)}")
        pdf.showPage()
    pdf.save()
    print(f"{theme}: page heights {', '.join(f'{measure(story):.1f}pt' for story in stories)} / {available:.1f}pt")


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
            link = html.parse(str(forwarding_page)).getroot().get_element_by_id("pdf-download").get("href")
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise ValueError(f"PDF destination must be a local file: {link}")
            path = (forwarding_page.parent / unquote(parsed.path)).resolve()
            expected = pdf_directory / f"{prefix}-{edition}-{theme}.pdf"
            if path != expected:
                raise ValueError(f"{theme} forwarding link must target {expected.relative_to(ROOT.parent)}")
            publications.append((document, theme, edition, path))

    # Prepare both complete pairs before publishing any final file. Per-file
    # replacement is atomic; the Git commit publishes the site as a complete set.
    with TemporaryDirectory(prefix="openhearted-pdfs-") as temporary:
        for index, (document, theme, edition, _) in enumerate(publications):
            write_pdf(Path(temporary) / f"{index}.pdf", document, theme, edition)
        for index, (_, _, _, destination) in enumerate(publications):
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_output = destination.with_suffix(".pdf.tmp")
            try:
                temporary_output.write_bytes((Path(temporary) / f"{index}.pdf").read_bytes())
                os.replace(temporary_output, destination)
            finally:
                temporary_output.unlink(missing_ok=True)
            print(destination)


if __name__ == "__main__":
    main()
