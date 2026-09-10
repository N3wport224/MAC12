import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from imessage_to_word.docx_writer import Document, Paragraph, Run, Table

try:
    import docx as python_docx
except ImportError:  # optional: only used to double-check our output
    python_docx = None

try:
    import mammoth
except ImportError:
    mammoth = None


def _pandoc():
    """pandoc is an entirely separate .docx implementation; use it if present."""
    return shutil.which("pandoc")

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

REQUIRED_PARTS = [
    "[Content_Types].xml",
    "_rels/.rels",
    "word/document.xml",
    "word/styles.xml",
    "word/footer1.xml",
    "word/_rels/document.xml.rels",
    "docProps/core.xml",
]


def build_sample(path: Path) -> Path:
    document = Document(title="Sample")
    document.add_paragraph([Run("Heading", bold=True, size=18, color="0B57D0")])
    document.add(Table([[[Run("Label", bold=True)], [Run("Value")]]], [1800, 6000]))
    document.add_paragraph(
        [Run('R&D <tags> "quoted"\nsecond line\twith tab')],
        shading="EEEEEE", border_left="0B57D0", indent_left=2448, align="left",
    )
    return document.save(path)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.path = build_sample(self.temp / "sample.docx")

    def test_every_required_part_is_present(self):
        with zipfile.ZipFile(self.path) as archive:
            names = archive.namelist()
        for part in REQUIRED_PARTS:
            self.assertIn(part, names)

    def test_content_types_is_the_first_entry(self):
        with zipfile.ZipFile(self.path) as archive:
            self.assertEqual(archive.namelist()[0], "[Content_Types].xml")

    def test_all_parts_are_well_formed_xml(self):
        with zipfile.ZipFile(self.path) as archive:
            for name in archive.namelist():
                ET.fromstring(archive.read(name))

    def test_special_characters_are_escaped(self):
        with zipfile.ZipFile(self.path) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("R&amp;D &lt;tags&gt;", body)
        self.assertNotIn("<tags>", body)

    def test_newlines_and_tabs_become_word_elements(self):
        with zipfile.ZipFile(self.path) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:br/>", body)
        self.assertIn("<w:tab/>", body)

    def test_paragraph_properties_use_schema_order(self):
        # Word rejects pPr children that are out of sequence.
        with zipfile.ZipFile(self.path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        order = ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "pBdr",
                 "shd", "spacing", "ind", "jc", "outlineLvl"]
        for properties in root.iter(W + "pPr"):
            seen = [child.tag[len(W):] for child in properties]
            positions = [order.index(tag) for tag in seen if tag in order]
            self.assertEqual(positions, sorted(positions), seen)

    def test_footer_carries_page_number_fields(self):
        with zipfile.ZipFile(self.path) as archive:
            footer = archive.read("word/footer1.xml").decode("utf-8")
        self.assertIn(" PAGE ", footer)
        self.assertIn(" NUMPAGES ", footer)

    @unittest.skipUnless(python_docx, "python-docx not installed")
    def test_word_libraries_can_read_the_file(self):
        document = python_docx.Document(str(self.path))
        texts = [paragraph.text for paragraph in document.paragraphs]
        self.assertIn("Heading", texts)
        self.assertEqual(document.core_properties.title, "Sample")
        self.assertEqual(len(document.tables), 1)
        self.assertEqual(
            [cell.text for cell in document.tables[0].rows[0].cells], ["Label", "Value"]
        )


class IndependentReaderTests(unittest.TestCase):
    """Three unrelated implementations should all accept the file Word will get."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.path = build_sample(self.temp / "sample.docx")

    @unittest.skipUnless(_pandoc(), "pandoc not installed")
    def test_pandoc_reads_it_without_warnings(self):
        completed = subprocess.run(
            [_pandoc(), "-f", "docx", "-t", "plain", str(self.path)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr.strip(), "")
        self.assertIn("Heading", completed.stdout)
        self.assertIn("Label", completed.stdout)

    @unittest.skipUnless(mammoth, "mammoth not installed")
    def test_mammoth_reads_it_without_warnings(self):
        with open(str(self.path), "rb") as handle:
            result = mammoth.convert_to_html(handle)
        self.assertEqual(list(result.messages), [])
        self.assertIn("Heading", result.value)


class RunTests(unittest.TestCase):
    def test_run_properties_use_schema_order(self):
        xml = Run("x", bold=True, italic=True, caps=True, color="FF0000",
                  size=9, font="Calibri", underline=True).to_xml()
        tags = ["rFonts", "b", "i", "smallCaps", "color", "sz", "u"]
        positions = [xml.index("<w:" + tag) for tag in tags]
        self.assertEqual(positions, sorted(positions))

    def test_size_is_written_in_half_points(self):
        self.assertIn('<w:sz w:val="21"/>', Run("x", size=10.5).to_xml())

    def test_empty_paragraph_is_valid(self):
        ET.fromstring(
            '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
            + Paragraph([]).to_xml()[len("<w:p"):]
        )


if __name__ == "__main__":
    unittest.main()
