"""A very small WordprocessingML (.docx) writer.

Only the pieces this app needs are implemented -- styled runs, paragraph
shading/indents/borders, a simple table and a page-number footer -- but the
output is a valid Office Open XML package that Word, Pages and Google Docs all
open.  Doing it by hand keeps the app dependency-free so it runs on a stock Mac
with ``python3`` and nothing installed.
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

# Twips (1/20 pt): 1 inch = 1440.
INCH = 1440


def esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def esc_attr(text: str) -> str:
    return esc(text).replace('"', "&quot;")


class Run:
    """A stretch of text with uniform formatting."""

    def __init__(
        self,
        text: str = "",
        bold: bool = False,
        italic: bool = False,
        color: Optional[str] = None,
        size: Optional[float] = None,   # points
        font: Optional[str] = None,
        caps: bool = False,
        underline: bool = False,
        break_before: bool = False,
    ):
        self.text = text
        self.bold = bold
        self.italic = italic
        self.color = color
        self.size = size
        self.font = font
        self.caps = caps
        self.underline = underline
        self.break_before = break_before

    def to_xml(self) -> str:
        properties = []
        if self.font:
            properties.append(
                '<w:rFonts w:ascii="{f}" w:hAnsi="{f}" w:cs="{f}"/>'.format(
                    f=esc_attr(self.font)
                )
            )
        if self.bold:
            properties.append("<w:b/>")
        if self.italic:
            properties.append("<w:i/>")
        if self.caps:
            properties.append("<w:smallCaps/>")
        if self.color:
            properties.append('<w:color w:val="{}"/>'.format(esc_attr(self.color)))
        if self.size:
            half_points = int(round(self.size * 2))
            properties.append('<w:sz w:val="{0}"/><w:szCs w:val="{0}"/>'.format(half_points))
        if self.underline:
            properties.append('<w:u w:val="single"/>')

        parts = ["<w:r>"]
        if properties:
            parts.append("<w:rPr>" + "".join(properties) + "</w:rPr>")
        if self.break_before:
            parts.append("<w:br/>")
        for index, line in enumerate((self.text or "").split("\n")):
            if index:
                parts.append("<w:br/>")
            for tab_index, piece in enumerate(line.split("\t")):
                if tab_index:
                    parts.append("<w:tab/>")
                if piece:
                    parts.append(
                        '<w:t xml:space="preserve">{}</w:t>'.format(esc(piece))
                    )
        parts.append("</w:r>")
        return "".join(parts)


class Paragraph:
    def __init__(
        self,
        runs: Optional[Sequence[Run]] = None,
        style: Optional[str] = None,
        align: Optional[str] = None,          # left | center | right | both
        indent_left: int = 0,
        indent_right: int = 0,
        space_before: int = 0,                # twips
        space_after: int = 0,
        line_spacing: Optional[int] = None,   # twips, exact line height
        shading: Optional[str] = None,        # hex fill
        border_left: Optional[str] = None,    # hex colour of a left accent bar
        border_bottom: Optional[str] = None,
        keep_next: bool = False,
        outline_level: Optional[int] = None,
        page_break_before: bool = False,
    ):
        self.runs = list(runs or [])
        self.style = style
        self.align = align
        self.indent_left = indent_left
        self.indent_right = indent_right
        self.space_before = space_before
        self.space_after = space_after
        self.line_spacing = line_spacing
        self.shading = shading
        self.border_left = border_left
        self.border_bottom = border_bottom
        self.keep_next = keep_next
        self.outline_level = outline_level
        self.page_break_before = page_break_before

    def to_xml(self) -> str:
        # Child order below follows the CT_PPrBase schema sequence.
        properties: List[str] = []
        if self.style:
            properties.append('<w:pStyle w:val="{}"/>'.format(esc_attr(self.style)))
        if self.keep_next:
            properties.append("<w:keepNext/><w:keepLines/>")
        if self.page_break_before:
            properties.append("<w:pageBreakBefore/>")
        borders = []
        if self.border_left:
            borders.append(
                '<w:left w:val="single" w:sz="18" w:space="8" w:color="{}"/>'.format(
                    esc_attr(self.border_left)
                )
            )
        if self.border_bottom:
            borders.append(
                '<w:bottom w:val="single" w:sz="6" w:space="4" w:color="{}"/>'.format(
                    esc_attr(self.border_bottom)
                )
            )
        if borders:
            properties.append("<w:pBdr>" + "".join(borders) + "</w:pBdr>")
        if self.shading:
            properties.append(
                '<w:shd w:val="clear" w:color="auto" w:fill="{}"/>'.format(
                    esc_attr(self.shading)
                )
            )
        spacing = []
        if self.space_before:
            spacing.append('w:before="{}"'.format(int(self.space_before)))
        if self.space_after or self.space_after == 0:
            spacing.append('w:after="{}"'.format(int(self.space_after)))
        if self.line_spacing:
            spacing.append('w:line="{}" w:lineRule="auto"'.format(int(self.line_spacing)))
        if spacing:
            properties.append("<w:spacing {}/>".format(" ".join(spacing)))
        if self.indent_left or self.indent_right:
            properties.append(
                '<w:ind w:left="{}" w:right="{}"/>'.format(
                    int(self.indent_left), int(self.indent_right)
                )
            )
        if self.align:
            properties.append('<w:jc w:val="{}"/>'.format(esc_attr(self.align)))
        if self.outline_level is not None:
            properties.append('<w:outlineLvl w:val="{}"/>'.format(int(self.outline_level)))

        parts = ["<w:p>"]
        if properties:
            parts.append("<w:pPr>" + "".join(properties) + "</w:pPr>")
        parts.extend(run.to_xml() for run in self.runs)
        parts.append("</w:p>")
        return "".join(parts)


class Table:
    """A borderless two-column style table used for the summary block."""

    def __init__(self, rows: Sequence[Sequence[Sequence[Run]]], widths: Sequence[int]):
        self.rows = rows
        self.widths = widths

    def to_xml(self) -> str:
        grid = "".join('<w:gridCol w:w="{}"/>'.format(int(w)) for w in self.widths)
        parts = [
            "<w:tbl><w:tblPr>",
            '<w:tblW w:w="0" w:type="auto"/>',
            '<w:tblLayout w:type="fixed"/>',
            '<w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="0" w:type="dxa"/>'
            '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="120" w:type="dxa"/></w:tblCellMar>',
            "</w:tblPr>",
            "<w:tblGrid>", grid, "</w:tblGrid>",
        ]
        for row in self.rows:
            parts.append("<w:tr>")
            for index, cell in enumerate(row):
                width = self.widths[index] if index < len(self.widths) else 2000
                parts.append(
                    '<w:tc><w:tcPr><w:tcW w:w="{}" w:type="dxa"/></w:tcPr>'.format(int(width))
                )
                parts.append(
                    Paragraph(cell, space_after=20, line_spacing=240).to_xml()
                )
                parts.append("</w:tc>")
            parts.append("</w:tr>")
        parts.append("</w:tbl>")
        return "".join(parts)


class Document:
    def __init__(
        self,
        title: str = "",
        author: str = "iMessage to Word",
        default_font: str = "Calibri",
        default_size: float = 11.0,
    ):
        self.title = title
        self.author = author
        self.default_font = default_font
        self.default_size = default_size
        self.blocks: List[object] = []

    # -- content -----------------------------------------------------------
    def add(self, block) -> None:
        self.blocks.append(block)

    def add_paragraph(self, *args, **kwargs) -> Paragraph:
        paragraph = Paragraph(*args, **kwargs)
        self.blocks.append(paragraph)
        return paragraph

    def add_spacer(self, height: int = 120) -> None:
        self.blocks.append(Paragraph([], space_after=height, line_spacing=120))

    # -- packaging ---------------------------------------------------------
    def _document_xml(self) -> str:
        body = "".join(block.to_xml() for block in self.blocks)
        # Word requires a paragraph after a table; a trailing empty one is safe.
        if self.blocks and isinstance(self.blocks[-1], Table):
            body += "<w:p/>"
        section = (
            "<w:sectPr>"
            '<w:footerReference w:type="default" r:id="rId3"/>'
            '<w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"'
            ' w:header="720" w:footer="600" w:gutter="0"/>'
            '<w:cols w:space="720"/>'
            "</w:sectPr>"
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="{w}" xmlns:r="{r}"><w:body>{body}{section}</w:body>'
            "</w:document>".format(w=W_NS, r=R_NS, body=body, section=section)
        )

    def _styles_xml(self) -> str:
        font = esc_attr(self.default_font)
        size = int(round(self.default_size * 2))
        heading = (
            '<w:style w:type="paragraph" w:styleId="Heading{level}">'
            '<w:name w:val="heading {level}"/><w:basedOn w:val="Normal"/>'
            '<w:qFormat/><w:pPr><w:keepNext/><w:outlineLvl w:val="{outline}"/></w:pPr>'
            '<w:rPr><w:b/><w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/></w:rPr></w:style>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="{w}">'
            "<w:docDefaults><w:rPrDefault><w:rPr>"
            '<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>'
            '<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>'
            "</w:rPr></w:rPrDefault>"
            "<w:pPrDefault><w:pPr>"
            '<w:spacing w:after="120" w:line="264" w:lineRule="auto"/>'
            "</w:pPr></w:pPrDefault></w:docDefaults>"
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
            '<w:name w:val="Normal"/><w:qFormat/></w:style>'
            "{h1}{h2}"
            "</w:styles>".format(
                w=W_NS,
                font=font,
                size=size,
                h1=heading.format(level=1, outline=0, sz=32),
                h2=heading.format(level=2, outline=1, sz=26),
            )
        )

    def _footer_xml(self) -> str:
        gray = '<w:rPr><w:color w:val="8A8A8E"/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>'
        def field(instruction: str) -> str:
            return (
                '<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
                '<w:r>{rpr}<w:instrText xml:space="preserve"> {instr} </w:instrText></w:r>'
                '<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
                "<w:r>{rpr}<w:t>1</w:t></w:r>"
                '<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>'
            ).format(rpr=gray, instr=instruction)

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:ftr xmlns:w="{w}" xmlns:r="{r}"><w:p>'
            '<w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="0"/></w:pPr>'
            '<w:r>{gray}<w:t xml:space="preserve">Page </w:t></w:r>{page}'
            '<w:r>{gray}<w:t xml:space="preserve"> of </w:t></w:r>{pages}'
            "</w:p></w:ftr>".format(
                w=W_NS, r=R_NS, gray=gray, page=field("PAGE"), pages=field("NUMPAGES")
            )
        )

    def _core_xml(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            "<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>"
            "<cp:lastModifiedBy>{author}</cp:lastModifiedBy>"
            '<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
            '<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
            "</cp:coreProperties>".format(
                title=esc(self.title), author=esc(self.author), stamp=stamp
            )
        )

    @staticmethod
    def _app_xml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
            'extended-properties">'
            "<Application>iMessage to Word</Application></Properties>"
        )

    @staticmethod
    def _content_types() -> str:
        override = '<Override PartName="/{part}" ContentType="{ct}"/>'
        wml = "application/vnd.openxmlformats-officedocument.wordprocessingml"
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
            'package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            + override.format(part="word/document.xml", ct=wml + ".document.main+xml")
            + override.format(part="word/styles.xml", ct=wml + ".styles+xml")
            + override.format(part="word/footer1.xml", ct=wml + ".footer+xml")
            + override.format(
                part="docProps/core.xml",
                ct="application/vnd.openxmlformats-package.core-properties+xml",
            )
            + override.format(
                part="docProps/app.xml",
                ct="application/vnd.openxmlformats-officedocument.extended-properties+xml",
            )
            + "</Types>"
        )

    @staticmethod
    def _package_rels() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships">'
            '<Relationship Id="rId1" Type="{r}/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/'
            'relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="{r}/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>".format(r=R_NS)
        )

    @staticmethod
    def _document_rels() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
            'relationships">'
            '<Relationship Id="rId1" Type="{r}/styles" Target="styles.xml"/>'
            '<Relationship Id="rId3" Type="{r}/footer" Target="footer1.xml"/>'
            "</Relationships>".format(r=R_NS)
        )

    def save(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        parts: Dict[str, str] = {
            "[Content_Types].xml": self._content_types(),
            "_rels/.rels": self._package_rels(),
            "docProps/core.xml": self._core_xml(),
            "docProps/app.xml": self._app_xml(),
            "word/_rels/document.xml.rels": self._document_rels(),
            "word/document.xml": self._document_xml(),
            "word/styles.xml": self._styles_xml(),
            "word/footer1.xml": self._footer_xml(),
        }
        with zipfile.ZipFile(str(path), "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content.encode("utf-8"))
        return path
