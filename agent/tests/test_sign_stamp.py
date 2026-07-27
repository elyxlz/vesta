"""Tests for the sign-service stamp.py argument parsing and placement geometry.

stamp.py defers its `import fitz` (PyMuPDF) into the functions that touch a PDF,
so the pure helpers (`signature_box`, `build_parser`) import and run without the
optional dependency installed.
"""

import importlib.util
import pathlib as pl

import pytest

STAMP_PY = pl.Path(__file__).resolve().parents[1] / "skills/sign-service/stamp.py"


def _load_stamp():
    spec = importlib.util.spec_from_file_location("sign_stamp", STAMP_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


stamp = _load_stamp()


def test_signature_box_is_below_and_left_aligned():
    # label at (100, 200)-(260, 212): box starts gap below the label bottom (212)
    # and is left-aligned to the label's x0.
    box = stamp.signature_box((100.0, 200.0, 260.0, 212.0), width=175.0, height=26.0, gap=1.0)
    assert box == (100.0, 213.0, 275.0, 239.0)


def test_signature_box_respects_dimensions():
    box = stamp.signature_box((0.0, 0.0, 10.0, 10.0), width=50.0, height=20.0, gap=5.0)
    x0, y0, x1, y1 = box
    assert x1 - x0 == 50.0
    assert y1 - y0 == 20.0
    assert y0 == 15.0  # label bottom (10) + gap (5)


def test_parser_requires_signature_label_and_outdir():
    parser = stamp.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["form.pdf"])  # missing required flags


def test_parser_collects_multiple_labels_and_pdfs():
    args = stamp.build_parser().parse_args(
        [
            "a.pdf",
            "b.pdf",
            "--signature",
            "sig.png",
            "--outdir",
            "out",
            "--label",
            "FIRMA del CONTRIBUENTE",
            "--label",
            "FIRMA DEL CONTRIBUENTE",
            "--page",
            "2",
            "--preview",
        ]
    )
    assert args.pdfs == ["a.pdf", "b.pdf"]
    assert args.labels == ["FIRMA del CONTRIBUENTE", "FIRMA DEL CONTRIBUENTE"]
    assert args.page == 2
    assert args.preview is True
    assert args.signature == "sig.png"


def test_parser_defaults():
    args = stamp.build_parser().parse_args(["form.pdf", "-s", "sig.png", "-o", "out", "-l", "Sign here"])
    assert args.page == 0
    assert args.width == 175.0
    assert args.height == 26.0
    assert args.gap == 1.0
    assert args.preview is False
    assert args.suffix == " (signed)"
