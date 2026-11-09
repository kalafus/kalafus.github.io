"""Shared typography and publication for the recovery resource PDFs.

Dependencies: reportlab and lxml. Both resource builders use the same embedded
Arial/Georgia fonts, light/dark palettes, page bounds, and atomic file publication.
"""

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
from reportlab.platypus import HRFlowable, Paragraph, TableStyle


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


def inline(element, *, internal_links=False):
    """Translate only the content's supported inline markup to PDF markup."""
    result = escape(element.text or "")
    for child in element:
        content = inline(child, internal_links=internal_links)
        if child.tag == "strong":
            result += f"<b>{content}</b>"
        elif child.tag == "em":
            result += f"<i>{content}</i>"
        elif child.tag == "a":
            href = child.get("href")
            if not urlsplit(href).scheme and not (internal_links and href.startswith('#')):
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


def measure(story):
    # The last block's trailing gap has no content to separate from it. Measure
    # the drawn extent so that empty space after the final line cannot overflow.
    total = sum(item.getSpaceBefore() + item.wrap(CONTENT_WIDTH, HEIGHT)[1] + item.getSpaceAfter() for item in story)
    return total - story[-1].getSpaceAfter()


def write_stories(path, stories, *, title, subtitle, label, edition, theme,
                  author="Independent, member-created resource",
                  keywords="recovery, connection, discernment, autonomy, support"):
    palette = PALETTES[theme]
    available = HEIGHT - MARGIN - BOTTOM
    for number, story in enumerate(stories, 1):
        required = measure(story)
        if required > available:
            raise ValueError(f"Page {number} needs {required:.1f}pt; only {available:.1f}pt available. Revise the layout explicitly.")

    pdf = canvas.Canvas(str(path), pagesize=(WIDTH, HEIGHT), pageCompression=1, invariant=1)
    pdf.setTitle(f"{title} | {label} | {edition} | {theme.title()}")
    pdf.setAuthor(author)
    pdf.setSubject(subtitle)
    pdf.setKeywords(keywords)
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


def pdf_destination(forwarding_page, expected):
    """Read and validate the destination owned by a permanent download page."""
    link = html.parse(str(forwarding_page)).getroot().get_element_by_id("pdf-download").get("href")
    parsed = urlsplit(link)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f"PDF destination must be a local file: {link}")
    path = (forwarding_page.parent / unquote(parsed.path)).resolve()
    if path != expected.resolve():
        raise ValueError(f"{forwarding_page.parent.name} forwarding link must target {expected}")
    return path


def publish_pdf_set(publications, render):
    """Prepare every edition before replacing any published file."""
    with TemporaryDirectory(prefix="recovery-pdfs-") as temporary:
        for index, (document, theme, edition, _) in enumerate(publications):
            render(Path(temporary) / f"{index}.pdf", document, theme, edition)
        for index, (_, _, _, destination) in enumerate(publications):
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_output = destination.with_suffix(".pdf.tmp")
            try:
                temporary_output.write_bytes((Path(temporary) / f"{index}.pdf").read_bytes())
                os.replace(temporary_output, destination)
            finally:
                temporary_output.unlink(missing_ok=True)
            print(destination)
