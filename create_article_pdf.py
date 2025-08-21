#!/usr/bin/env python3
# /// script
# dependencies = [
#   "reportlab",
#   "markdown2",
# ]
# ///

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
from reportlab.lib.colors import HexColor
import markdown2
import re

def create_pdf():
    # Read the markdown file
    with open('beirut_port_article.md', 'r') as f:
        content = f.read()
    
    # Create PDF
    pdf_file = "beirut_port_commemoration_article.pdf"
    doc = SimpleDocTemplate(
        pdf_file,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )
    
    # Container for the 'Flowable' objects
    elements = []
    
    # Define styles
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=HexColor('#1a1a1a'),
        spaceAfter=6,
        alignment=TA_CENTER
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=14,
        textColor=HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=12
    )
    
    author_style = ParagraphStyle(
        'Author',
        parent=styles['Normal'],
        fontSize=11,
        textColor=HexColor('#444444'),
        alignment=TA_CENTER,
        spaceAfter=20
    )
    
    heading2_style = ParagraphStyle(
        'CustomHeading2',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=HexColor('#2c3e50'),
        spaceBefore=12,
        spaceAfter=6
    )
    
    heading3_style = ParagraphStyle(
        'CustomHeading3',
        parent=styles['Heading3'],
        fontSize=14,
        textColor=HexColor('#34495e'),
        spaceBefore=10,
        spaceAfter=6
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_JUSTIFY,
        spaceAfter=10,
        leading=14
    )
    
    quote_style = ParagraphStyle(
        'Quote',
        parent=styles['Normal'],
        fontSize=12,
        leftIndent=20,
        rightIndent=20,
        textColor=HexColor('#2c3e50'),
        alignment=TA_JUSTIFY,
        spaceBefore=10,
        spaceAfter=10,
        leading=16
    )
    
    # Parse content line by line
    lines = content.split('\n')
    
    for i, line in enumerate(lines):
        line = line.strip()
        
        if not line:
            elements.append(Spacer(1, 0.2*inch))
            continue
            
        # Title
        if line.startswith('# '):
            text = line[2:]
            elements.append(Paragraph(text, title_style))
            
        # Subtitle (PORT BLAST COMMEMORATION)
        elif line.startswith('**PORT BLAST COMMEMORATION**'):
            text = line.replace('**', '')
            elements.append(Paragraph(text, subtitle_style))
            
        # Author line
        elif line.startswith('By '):
            elements.append(Paragraph(line, author_style))
            
        # Date line
        elif re.match(r'^[A-Z][a-z]+ \d+, \d{4}', line):
            elements.append(Paragraph(line, author_style))
            
        # Publisher
        elif line == '*L\'Orient-Le Jour*':
            elements.append(Paragraph('L\'Orient-Le Jour', author_style))
            
        # Heading 2
        elif line.startswith('## '):
            text = line[3:]
            elements.append(Paragraph(text, heading2_style))
            
        # Heading 3
        elif line.startswith('### '):
            text = line[4:]
            elements.append(Paragraph(text, heading3_style))
            
        # List items with numbers
        elif re.match(r'^\d+\.\s+\*\*', line):
            # Bold list items - handle properly
            parts = line.split('**')
            if len(parts) > 1:
                result = []
                for i, part in enumerate(parts):
                    result.append(part)
                    if i < len(parts) - 1:
                        if i % 2 == 0:
                            result.append('<b>')
                        else:
                            result.append('</b>')
                text = ''.join(result)
            else:
                text = line
            elements.append(Paragraph(text, body_style))
            
        # Bullet points
        elif line.startswith('- '):
            text = '• ' + line[2:]
            # Handle bold text properly
            parts = text.split('**')
            if len(parts) > 1:
                result = []
                for i, part in enumerate(parts):
                    result.append(part)
                    if i < len(parts) - 1:
                        if i % 2 == 0:
                            result.append('<b>')
                        else:
                            result.append('</b>')
                text = ''.join(result)
            elements.append(Paragraph(text, body_style))
            
        # Key Quote
        elif '**"I can\'t give a date' in line:
            # Handle bold text properly
            parts = line.split('**')
            if len(parts) > 1:
                result = []
                for i, part in enumerate(parts):
                    result.append(part)
                    if i < len(parts) - 1:
                        if i % 2 == 0:
                            result.append('<b>')
                        else:
                            result.append('</b>')
                text = ''.join(result)
            else:
                text = line
            elements.append(Paragraph(text, quote_style))
            
        # Horizontal rule
        elif line == '---':
            elements.append(Spacer(1, 0.1*inch))
            
        # Regular text
        elif line and not line.startswith('#'):
            # Convert markdown bold to HTML more carefully
            text = line
            # Replace pairs of ** with <b> and </b>
            parts = text.split('**')
            if len(parts) > 1:
                result = []
                for i, part in enumerate(parts):
                    result.append(part)
                    if i < len(parts) - 1:
                        if i % 2 == 0:
                            result.append('<b>')
                        else:
                            result.append('</b>')
                text = ''.join(result)
                
            elements.append(Paragraph(text, body_style))
    
    # Build PDF
    doc.build(elements)
    print(f"PDF created successfully: {pdf_file}")
    return pdf_file

if __name__ == "__main__":
    pdf_file = create_pdf()