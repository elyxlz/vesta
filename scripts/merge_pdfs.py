#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "pypdf",
# ]
# ///

from pypdf import PdfReader, PdfWriter
import sys
from pathlib import Path

def merge_pdfs(pdf1_path: str, pdf2_path: str, output_path: str) -> None:
    writer = PdfWriter()
    
    pdf1 = PdfReader(pdf1_path)
    for page in pdf1.pages:
        writer.add_page(page)
    
    pdf2 = PdfReader(pdf2_path)
    for page in pdf2.pages:
        writer.add_page(page)
    
    with open(output_path, 'wb') as output_file:
        writer.write(output_file)
    
    print(f"Successfully merged PDFs into: {output_path}")
    print(f"Total pages: {len(writer.pages)}")

if __name__ == "__main__":
    base_path = Path("/home/elyx/vesta")
    
    pdf1 = base_path / "prescrizione_rx.pdf"
    pdf2 = base_path / "prescrizione_trattamenti.pdf"
    output = base_path / "prescrizioni_chiropratico.pdf"
    
    if not pdf1.exists():
        print(f"Error: {pdf1} not found")
        sys.exit(1)
    
    if not pdf2.exists():
        print(f"Error: {pdf2} not found")
        sys.exit(1)
    
    merge_pdfs(str(pdf1), str(pdf2), str(output))