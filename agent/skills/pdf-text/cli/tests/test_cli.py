import pathlib as pl

import pymupdf
import pytest
from pdf_text_cli import cli

EMPTY_CMAP = b"/CIDInit /ProcSet findresource begin\nbegincmap\n1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\nendcmap\nend\n"
MAPPED_CMAP = EMPTY_CMAP.replace(b"endcmap", b"1 beginbfchar\n<0056> <03C3>\nendbfchar\nendcmap")
BROKEN = "/Type /Font /Subtype /Type0 /BaseFont /BBBBBB+Broken /Encoding /Identity-H"
MAPPED = "/Type /Font /Subtype /Type0 /BaseFont /CCCCCC+Mapped /Encoding /Identity-H"
PLAIN = "/Type /Font /Subtype /TrueType /BaseFont /AAAAAA+Plain /Encoding /WinAnsiEncoding"


def add_font(doc: pymupdf.Document, page: pymupdf.Page, resource: str, font: str, cmap: bytes | None) -> None:
    if cmap is not None:
        cmap_xref = doc.get_new_xref()
        doc.update_object(cmap_xref, "<<>>")
        doc.update_stream(cmap_xref, cmap)
        font = f"{font} /ToUnicode {cmap_xref} 0 R"
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, f"<< {font} >>")
    resources_xref = int(doc.xref_get_key(page.xref, "Resources")[1].split()[0])
    doc.xref_set_key(resources_xref, f"Font/{resource}", f"{font_xref} 0 R")


def write_pdf(path: pl.Path, pages: list[list[tuple[str, str, bytes | None]]]) -> pl.Path:
    doc = pymupdf.open()
    for fonts in pages:
        page = doc.new_page()
        for resource, font, cmap in fonts:
            add_font(doc, page, resource, font, cmap)
    doc.save(path)
    return path


def test_identity_h_font_with_an_empty_tounicode_is_flagged_with_its_pages(tmp_path, capsys):
    pdf = write_pdf(
        tmp_path / "broken.pdf",
        [[("FOK", PLAIN, None)], [("FBAD", BROKEN, EMPTY_CMAP)], [("FBAD", BROKEN, EMPTY_CMAP), ("FOK", PLAIN, None)]],
    )
    assert cli.main([str(pdf)]) == 1
    assert capsys.readouterr().out == "BBBBBB+Broken pages 2,3\n"


def test_identity_h_font_with_no_tounicode_is_flagged(tmp_path, capsys):
    pdf = write_pdf(tmp_path / "missing.pdf", [[("FBAD", BROKEN, None)]])
    assert cli.main([str(pdf)]) == 1
    assert capsys.readouterr().out == "BBBBBB+Broken pages 1\n"


@pytest.mark.parametrize(
    "fonts",
    [
        [("FOK", MAPPED, MAPPED_CMAP)],
        [("FOK", PLAIN, None)],
        [],
    ],
)
def test_mapped_and_simple_fonts_are_silent(tmp_path, capsys, fonts):
    pdf = write_pdf(tmp_path / "clean.pdf", [fonts])
    assert cli.main([str(pdf)]) == 0
    assert capsys.readouterr().out == ""


def test_unreadable_input_fails_on_stderr(tmp_path, capsys):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    assert cli.main([str(junk)]) == 2
    assert cli.main([str(tmp_path / "absent.pdf")]) == 2
    assert cli.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("\n") == 3
