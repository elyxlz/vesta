#!/usr/bin/env python3
# /// script
# dependencies = [
#   "weasyprint",
#   "jinja2",
# ]
# ///
"""
BASc Employability PESTEL Analysis Generator
"""

from jinja2 import Template
from weasyprint import HTML
import os

# PESTEL data
pestel_data = {
    'Political': [
        'Graduate visa policies (2-year post-study work visa)',
        'Higher education funding cuts',
        'Brexit impact on EU student employment'
    ],
    'Economic': [
        'Economic recession reducing graduate job openings',
        'High cost of living in London affecting job choice',
        'Startup ecosystem funding drought'
    ],
    'Social': [
        'Employer bias against "generalist" degrees',
        'Limited alumni network (new program)',
        'Class privilege in unpaid internship culture'
    ],
    'Technological': [
        'AI automating entry-level jobs',
        'Remote work creating global competition',
        'Digital skills gap in traditional industries'
    ],
    'Environmental': [
        'Green economy creating new job types',
        'ESG requirements creating interdisciplinary roles',
        'Climate change forcing industry transitions'
    ],
    'Legal': [
        'Employment law changes (IR35, gig economy)',
        'Professional qualification requirements',
        'Data protection laws affecting recruitment processes'
    ]
}

# Color scheme for each category
colors = {
    'Political': '#e76f51',      # coral red
    'Economic': '#2a9d8f',       # teal
    'Social': '#e9c46a',         # yellow
    'Technological': '#4d96ff',  # blue
    'Environmental': '#6bcf7f',  # green
    'Legal': '#9d4edd'          # purple
}

# HTML template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>PESTEL Analysis - BASc Employability</title>
    <style>
        @page {
            size: A4;
            margin: 2cm;
        }

        body {
            font-family: 'Helvetica', 'Arial', sans-serif;
            font-size: 10pt;
            line-height: 1.4;
            color: #333;
        }

        h1 {
            font-size: 22pt;
            font-weight: bold;
            color: #1a1a1a;
            text-align: center;
            margin-bottom: 0.3em;
            border-bottom: 3px solid #2a9d8f;
            padding-bottom: 0.3em;
        }

        .subtitle {
            text-align: center;
            font-size: 11pt;
            color: #666;
            margin-bottom: 1.5em;
            font-style: italic;
        }

        .pestel-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1em;
            margin-top: 1em;
        }

        .pestel-box {
            border-left: 5px solid;
            padding: 0.8em 1em;
            background-color: #f8f9fa;
            break-inside: avoid;
        }

        .pestel-box h2 {
            font-size: 14pt;
            font-weight: bold;
            margin: 0 0 0.5em 0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .pestel-box ul {
            margin: 0;
            padding-left: 1.2em;
            list-style-type: disc;
        }

        .pestel-box li {
            margin-bottom: 0.4em;
            line-height: 1.5;
        }

        {% for category, color in colors.items() %}
        .box-{{ category|lower }} {
            border-left-color: {{ color }};
        }
        .box-{{ category|lower }} h2 {
            color: {{ color }};
        }
        {% endfor %}

        .footer {
            margin-top: 2em;
            padding-top: 1em;
            border-top: 1px solid #ccc;
            font-size: 8pt;
            color: #666;
            text-align: center;
        }
    </style>
</head>
<body>
    <h1>PESTEL Analysis</h1>
    <p class="subtitle">BASc Employability Problem - External Environment Factors</p>

    <div class="pestel-grid">
        {% for category in ['Political', 'Economic', 'Social', 'Technological', 'Environmental', 'Legal'] %}
        <div class="pestel-box box-{{ category|lower }}">
            <h2>{{ category }}</h2>
            <ul>
                {% for item in data[category] %}
                <li>{{ item }}</li>
                {% endfor %}
            </ul>
        </div>
        {% endfor %}
    </div>

    <div class="footer">
        <p>BASc Employability PESTEL Analysis • UCL Knowledge Economy • October 2025</p>
    </div>
</body>
</html>
"""

def generate_pestel():
    """Generate PESTEL diagram PDF"""
    print("=" * 60)
    print("PESTEL ANALYSIS DIAGRAM GENERATOR")
    print("=" * 60)
    print()

    print("Generating PESTEL diagram...")

    # Render HTML
    template = Template(HTML_TEMPLATE)
    html_content = template.render(data=pestel_data, colors=colors)

    # Convert to PDF
    output_file = 'basc_employability_pestel.pdf'
    HTML(string=html_content).write_pdf(output_file)

    print(f"\n✓ PESTEL diagram generated successfully: {output_file}")
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)

    # Open in browser
    print("\nOpening PDF in Brave browser...")
    try:
        pdf_path = os.path.abspath(output_file)
        import subprocess
        subprocess.Popen(['brave-browser', pdf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Browser opened!")
    except Exception as e:
        print(f"⚠ Could not open browser automatically: {e}")
        print(f"Open manually: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    try:
        generate_pestel()
    except Exception as e:
        print(f"\n✗ Error generating PESTEL diagram: {e}")
        import traceback
        traceback.print_exc()
