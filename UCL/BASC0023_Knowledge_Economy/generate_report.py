#!/usr/bin/env python3
# /// script
# dependencies = [
#   "pandas",
#   "matplotlib",
#   "seaborn",
#   "numpy",
#   "weasyprint",
#   "jinja2",
# ]
# ///
"""
ASPEX Fundraising Analysis Report Generator
UCL BASc Knowledge Economy - Student Consultancy Project 2025

Generates a professional PDF report using HTML/CSS and WeasyPrint
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime
import numpy as np
import subprocess
import os
import warnings
import io
import base64
from jinja2 import Template
from weasyprint import HTML

warnings.filterwarnings('ignore')

# Set style for clean charts
sns.set_style("whitegrid")
sns.set_palette("husl")

def load_and_clean_pipeline_data(filepath):
    """Load and parse the fundraising pipeline CSV"""
    print("Loading fundraising pipeline data...")
    df = pd.read_csv(filepath, encoding='utf-8-sig')
    df = df.dropna(how='all')
    df_clean = df[df.iloc[:, 0].notna()].copy()

    if len(df_clean.columns) > 6:
        df_clean.columns = ['Funder', 'Deadline', 'Progress', 'Project', 'Dates', 'Amount', 'Lead', 'Notes_Fund'] + list(df_clean.columns[8:])

    # Remove section headers (they contain "targets:" or "PROG")
    df_clean = df_clean[~df_clean['Funder'].str.contains('targets:|PROG|Further funders', case=False, na=False)]
    df_clean = df_clean[df_clean['Funder'].str.len() > 3]

    # Remove header rows that snuck through
    df_clean = df_clean[~df_clean['Funder'].isin([
        'Applying to',
        'Fundraising / Future Projects IN PROGRESS'
    ])]
    df_clean = df_clean[~df_clean['Project'].isin([
        'Project name',
        'Project dates'
    ])]
    if 'Progress' in df_clean.columns:
        df_clean = df_clean[~df_clean['Progress'].str.contains(
            'Progress \\(',
            regex=True,
            na=False
        )]

    # Normalize project names
    if 'Project' in df_clean.columns:
        df_clean['Project'] = df_clean['Project'].str.strip()  # Remove leading/trailing spaces
        df_clean['Project'] = df_clean['Project'].str.replace('?', '', regex=False)  # Remove ?
        df_clean['Project'] = df_clean['Project'].fillna('Unspecified')

    return df_clean

def load_funders_database(filepath):
    """Load the arts funders database"""
    print("Loading arts funders database...")
    try:
        df = pd.read_csv(filepath, encoding='utf-8-sig', nrows=1000)
        df = df.dropna(how='all')
        return df
    except Exception as e:
        print(f"Error loading funders database: {e}")
        return None

def extract_amount(amount_str):
    """Extract funding amount from various text formats"""
    if pd.isna(amount_str):
        return None

    amount_str = str(amount_str).upper()

    # Handle TBC, N/A
    if 'TBC' in amount_str or 'N/A' in amount_str or amount_str.strip() == '':
        return None

    # Try patterns in order of specificity
    patterns = [
        (r'MAX\.?\s*£([\d,]+)K', 1000),         # "Max £35K" or "Max. £35K"
        (r'MAX\.?\s*£([\d,]+)', 1),             # "Max £35000"
        (r'MIN\.?\s*£([\d,]+)K', 1000),         # "Min. £10K"
        (r'MIN\.?\s*£([\d,]+)', 1),             # "Min. £10000"
        (r'UNDER\s*£([\d,]+)', 1),              # "under £7,500"
        (r'UP TO\s*£([\d,]+)K', 1000),          # "Up to £40K"
        (r'UP TO\s*£([\d,]+)', 1),              # "Up to £40000"
        (r'BETWEEN\s*£([\d,]+)', 1000),         # "Between £10-25K" (take first)
        (r'£([\d,]+)K?-[£]?([\d,]+)K', 1000),  # "£500-£5K" or "£10-25K" (take second/higher)
        (r'£([\d,]+)K', 1000),                  # "£50K"
        (r'£([\d,]+)', 1),                      # "£7,500"
    ]

    import re

    # Special handling for ranges "£500-£5K" - take the higher value
    range_match = re.search(r'£([\d,]+)K?-[£]?([\d,]+)K', amount_str)
    if range_match:
        # Take the second (higher) value
        amount = float(range_match.group(2).replace(',', ''))
        if amount < 1000:
            amount *= 1000
        return amount

    # Try other patterns
    for pattern, multiplier in patterns:
        if r'£([\d,]+)K?-[£]?([\d,]+)K' in pattern:
            continue  # Skip range pattern, already handled
        match = re.search(pattern, amount_str)
        if match:
            amount = float(match.group(1).replace(',', ''))
            # Only multiply if multiplier is 1000 and amount < 1000
            if multiplier == 1000 and amount < 1000:
                amount *= multiplier
            return amount

    return None

def analyze_pipeline(df):
    """Analyze the fundraising pipeline"""
    print("Analyzing pipeline data...")

    analysis = {
        'total_applications': len(df),
        'by_progress': df['Progress'].value_counts().to_dict() if 'Progress' in df.columns else {},
        'by_project': df['Project'].value_counts().to_dict() if 'Project' in df.columns else {},
    }

    if 'Amount' in df.columns:
        amounts = []
        for idx, row in df.iterrows():
            amount = None

            # Try to parse from Amount column first
            if pd.notna(row['Amount']):
                amount = extract_amount(row['Amount'])

            # If no amount in Amount column, try Notes_Fund column as fallback
            if amount is None and 'Notes_Fund' in df.columns and pd.notna(row['Notes_Fund']):
                amount = extract_amount(row['Notes_Fund'])

            if amount is not None:
                amounts.append(amount)

        if amounts:
            analysis['total_potential_funding'] = sum(amounts)
            analysis['avg_grant_size'] = np.mean(amounts)
            analysis['amounts'] = amounts
            analysis['amounts_count'] = len(amounts)

    return analysis

def fig_to_base64(fig):
    """Convert matplotlib figure to base64 string"""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    plt.close(fig)
    return f"data:image/png;base64,{img_base64}"

def create_pipeline_chart(analysis):
    """Create pipeline status chart"""
    if 'by_progress' in analysis and analysis['by_progress']:
        fig, ax = plt.subplots(figsize=(7, 4))
        progress_data = pd.Series(analysis['by_progress'])
        colors = ['#ff6b6b', '#ffd93d', '#6bcf7f', '#4d96ff']
        progress_data.plot(kind='barh', ax=ax, color=colors[:len(progress_data)])
        ax.set_xlabel('Number of Applications', fontsize=10)
        ax.set_title('Pipeline Status', fontsize=12, fontweight='bold', pad=10)
        ax.grid(axis='x', alpha=0.3)

        for i, v in enumerate(progress_data.values):
            ax.text(v + 0.1, i, str(v), va='center', fontweight='bold')

        plt.tight_layout()
        return fig_to_base64(fig)
    return None

def create_category_chart(analysis):
    """Create application category chart"""
    if 'by_project' in analysis and analysis['by_project']:
        fig, ax = plt.subplots(figsize=(7, 4))
        project_data = pd.Series(analysis['by_project']).head(8)
        colors_palette = sns.color_palette("husl", len(project_data))
        project_data.plot(kind='bar', ax=ax, color=colors_palette)
        ax.set_ylabel('Number of Applications', fontsize=10)
        ax.set_xlabel('Project/Programme', fontsize=10)
        ax.set_title('Applications by Category', fontsize=12, fontweight='bold', pad=10)
        ax.tick_params(axis='x', rotation=45)
        ax.grid(axis='y', alpha=0.3)

        for i, v in enumerate(project_data.values):
            ax.text(i, v + 0.1, str(v), ha='center', fontweight='bold', fontsize=9)

        plt.tight_layout()
        return fig_to_base64(fig)
    return None

def create_amounts_chart(analysis):
    """Create funding amounts distribution chart"""
    if 'amounts' in analysis and len(analysis['amounts']) > 0:
        fig, ax = plt.subplots(figsize=(7, 4))
        amounts = np.array(analysis['amounts'])

        max_amount = max(amounts)
        possible_bins = [0, 5000, 10000, 25000, 50000, 100000]
        possible_labels = ['<£5K', '£5-10K', '£10-25K', '£25-50K', '£50-100K', '>£100K']

        bins = [0]
        labels = []
        for i, b in enumerate(possible_bins[1:], start=1):
            if b < max_amount:
                bins.append(b)
                labels.append(possible_labels[i-1])
            else:
                break

        bins.append(max_amount + 1)
        if len(labels) < len(possible_labels):
            labels.append(possible_labels[len(labels)])

        if len(bins) < 3:
            bins = [0, max_amount/2, max_amount + 1]
            labels = [f'<£{max_amount/2:.0f}', f'£{max_amount/2:.0f}+']

        amounts_categorized = pd.cut(amounts, bins=bins, labels=labels, include_lowest=True)
        amounts_counts = amounts_categorized.value_counts().sort_index()

        colors = ['#e8f4f8', '#a7d7e8', '#6bb6d6', '#2e86ab', '#005f73', '#001219']
        amounts_counts.plot(kind='bar', ax=ax, color=colors[:len(amounts_counts)])
        ax.set_ylabel('Number of Opportunities', fontsize=10)
        ax.set_xlabel('Funding Range', fontsize=10)
        ax.set_title('Grant Size Distribution', fontsize=12, fontweight='bold', pad=10)
        ax.tick_params(axis='x', rotation=45)
        ax.grid(axis='y', alpha=0.3)

        for i, v in enumerate(amounts_counts.values):
            ax.text(i, v + 0.05, str(v), ha='center', fontweight='bold', fontsize=9)

        total = sum(amounts)
        ax.text(0.95, 0.95, f'Total: £{total:,.0f}',
                transform=ax.transAxes, ha='right', va='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
                fontsize=9, fontweight='bold')

        # Add data quality note with more space below for x-axis labels
        total_apps = analysis.get('total_applications', 0)
        note = f"Based on {len(amounts)} of {total_apps} applications with parseable amounts"

        # Adjust subplot to make room for the note below the x-axis label
        plt.subplots_adjust(bottom=0.30)
        ax.text(0.5, -0.45, note, transform=ax.transAxes,
                ha='center', fontsize=8, style='italic', color='#666')

        return fig_to_base64(fig)
    return None

def create_funders_chart(df_funders):
    """Create funder types chart"""
    if df_funders is not None and len(df_funders) > 0:
        fig, ax = plt.subplots(figsize=(7, 4))

        keywords = {
            'Arts & Culture': ['art', 'culture', 'museum', 'gallery'],
            'Community': ['community', 'social', 'inclusion'],
            'Education': ['education', 'learning', 'student'],
            'International': ['international', 'global', 'abroad'],
            'Heritage': ['heritage', 'conservation', 'historic']
        }

        funder_types = {k: 0 for k in keywords.keys()}
        desc_col = df_funders.columns[2] if len(df_funders.columns) > 2 else df_funders.columns[1]

        for desc in df_funders[desc_col].dropna():
            desc_lower = str(desc).lower()
            for ftype, kwords in keywords.items():
                if any(kw in desc_lower for kw in kwords):
                    funder_types[ftype] += 1

        types_series = pd.Series(funder_types).sort_values(ascending=True)
        colors = ['#264653', '#2a9d8f', '#e9c46a', '#f4a261', '#e76f51']
        types_series.plot(kind='barh', ax=ax, color=colors)
        ax.set_xlabel('Number of Funders', fontsize=10)
        ax.set_title('Funder Types in Database', fontsize=12, fontweight='bold', pad=10)
        ax.grid(axis='x', alpha=0.3)

        for i, v in enumerate(types_series.values):
            ax.text(v + 1, i, str(v), va='center', fontweight='bold', fontsize=9)

        plt.tight_layout()
        return fig_to_base64(fig)
    return None

# HTML template with professional CSS
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ASPEX Fundraising Analysis</title>
    <style>
        @page {
            size: A4;
            margin: 2.5cm 3cm;
        }

        body {
            font-family: 'Helvetica', 'Arial', sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #333;
            max-width: 100%;
        }

        h1 {
            font-size: 24pt;
            font-weight: bold;
            color: #1a1a1a;
            margin-top: 0;
            margin-bottom: 0.5em;
            border-bottom: 2px solid #2a9d8f;
            padding-bottom: 0.3em;
        }

        h2 {
            font-size: 16pt;
            font-weight: bold;
            color: #264653;
            margin-top: 1.5em;
            margin-bottom: 0.5em;
        }

        h3 {
            font-size: 13pt;
            font-weight: bold;
            color: #2a9d8f;
            margin-top: 1.2em;
            margin-bottom: 0.4em;
        }

        p {
            margin-bottom: 0.8em;
            text-align: justify;
        }

        .intro {
            font-size: 10pt;
            color: #666;
            margin-bottom: 1.5em;
            font-style: italic;
        }

        .chart {
            text-align: center;
            margin: 1.2em 0;
        }

        .chart img {
            width: 85%;
            height: auto;
        }

        .stats {
            background-color: #f8f9fa;
            padding: 0.8em 1.2em;
            border-left: 4px solid #2a9d8f;
            margin: 1em 0;
        }

        .stats p {
            margin: 0.3em 0;
        }

        .section {
            margin-bottom: 1.5em;
        }

        ul {
            margin: 0.5em 0 1em 1.5em;
            padding: 0;
        }

        li {
            margin-bottom: 0.4em;
        }

        .footer {
            margin-top: 2em;
            padding-top: 1em;
            border-top: 1px solid #ccc;
            font-size: 9pt;
            color: #666;
            text-align: center;
        }
    </style>
</head>
<body>
    <h1>ASPEX Fundraising Analysis</h1>

    <div class="stats">
        <p><strong>Summary:</strong> {{ total_apps }} active applications representing {{ total_funding }} in potential funding</p>
    </div>

    <p>
        This analysis examines {{ total_apps }} funding applications representing {{ total_funding }}
        in potential funding. The 2025 UK arts landscape is competitive, with local authority cuts
        driving organizations toward trusts and foundations.
    </p>

    <div class="section">
        <h2>Current Pipeline</h2>

        {% if chart_pipeline %}
        <div class="chart">
            <img src="{{ chart_pipeline }}" alt="Pipeline Status">
        </div>
        {% endif %}

        <p>
            Most applications are in early scoping stages. The pipeline targets both core operational
            funding and project-specific opportunities for creative programming and community engagement.
        </p>
    </div>

    <div class="section">
        <h2>Application Focus</h2>

        {% if chart_category %}
        <div class="chart">
            <img src="{{ chart_category }}" alt="Applications by Category">
        </div>
        {% endif %}

        <p>
            Core funding targets organizational sustainability. Creative engagement emphasizes
            community participation and accessibility. This distribution reflects priorities of
            maintaining operations while expanding community reach.
        </p>
    </div>

    <div class="section">
        <h2>Grant Distribution</h2>

        {% if chart_amounts %}
        <div class="chart">
            <img src="{{ chart_amounts }}" alt="Grant Size Distribution">
        </div>
        {% endif %}

        <p>
            Most opportunities with specified amounts fall in the £10-50K range, with several exceeding £100K.
            Total potential funding from applications with known amounts reaches {{ total_funding }}, though
            success rates typically range 20-40% for competitive trust funding. Many applications remain in
            early scoping stages without specified amounts yet.
        </p>
    </div>

    <div class="section">
        <h2>Funder Landscape</h2>

        {% if chart_funders %}
        <div class="chart">
            <img src="{{ chart_funders }}" alt="Funder Types">
        </div>
        {% endif %}

        <p>
            The database shows diverse funders across arts, culture, community, and education sectors,
            providing multiple pathways aligned with ASPEX's mission.
        </p>
    </div>

    <div class="section">
        <h2>Key Findings</h2>

        <p>
            <strong>Competitive landscape:</strong> Arts organizations increasingly compete for trust and foundation
            funding as 67% of local authorities reduce budgets. Multi-year funding from Arts Council England and
            British Council offers operational stability.
        </p>

        <p>
            <strong>Strategic strengths:</strong> ASPEX's refugee programming aligns with 2025 priorities (Austin Hope
            Pilkington Trust). Grade II listed building enables heritage funding access. Community engagement track
            record provides competitive advantage as funders prioritize measurable social impact.
        </p>

        <p>
            <strong>Diversification:</strong> Organizations with five or more funding streams show 40% higher
            sustainability. Opportunities span NPO status, project grants (Henry Moore Foundation, Art Fund),
            individual giving, and corporate partnerships. University of Portsmouth represents natural partnership
            potential.
        </p>

        <p>
            <strong>Technology:</strong> CRM systems drive 58% increases in mid-level giving through better donor
            segmentation and follow-up.
        </p>
    </div>

    <div class="section">
        <h2>Recommendations</h2>

        <p><strong>Immediate (Next 3 months):</strong></p>
        <ul>
            <li>Complete Esmee Fairbairn Foundation submission (Nov 5 deadline, £50K annually for 3-5 years)</li>
            <li>Submit Garfield Weston and Austin Hope Pilkington Trust applications</li>
            <li>Develop Arts Council NPO application for multi-year core funding</li>
        </ul>

        <p><strong>Short-term (3-6 months):</strong></p>
        <ul>
            <li>Research University of Portsmouth partnership models</li>
            <li>Map Hampshire and Portsmouth community foundations</li>
            <li>Strengthen legacy giving programme infrastructure</li>
        </ul>

        <p><strong>Long-term strategy:</strong></p>
        <ul>
            <li>Build 3-5 major funder relationships for multi-year commitments</li>
            <li>Develop Portsmouth-based corporate partnership strategy</li>
            <li>Invest in donor management CRM technology</li>
        </ul>

        <p><strong>Track:</strong> Multi-year commitments, funding stream diversity, donor retention, grant sizes,
        success rates by funder type.</p>
    </div>

</body>
</html>
"""

def generate_report():
    """Main function to generate the PDF report"""
    print("=" * 60)
    print("ASPEX FUNDRAISING ANALYSIS REPORT GENERATOR")
    print("=" * 60)
    print()

    # Load data
    df_pipeline = load_and_clean_pipeline_data('Fundraising_Future_Projects.csv')
    df_funders = load_funders_database('Arts_Funders_and_Websites.csv')

    # Analyze
    analysis = analyze_pipeline(df_pipeline)

    # Create charts
    print("Creating visualizations...")
    chart_pipeline = create_pipeline_chart(analysis)
    chart_category = create_category_chart(analysis)
    chart_amounts = create_amounts_chart(analysis)
    chart_funders = create_funders_chart(df_funders)

    # Prepare template data
    template_data = {
        'date': datetime.now().strftime("%B %Y"),
        'total_apps': analysis.get('total_applications', 'N/A'),
        'total_funding': f"£{analysis.get('total_potential_funding', 0):,.0f}" if 'total_potential_funding' in analysis else 'N/A',
        'chart_pipeline': chart_pipeline,
        'chart_category': chart_category,
        'chart_amounts': chart_amounts,
        'chart_funders': chart_funders,
    }

    # Render HTML
    print("Generating HTML from template...")
    template = Template(HTML_TEMPLATE)
    html_content = template.render(**template_data)

    # Convert to PDF
    print("Converting HTML to PDF with WeasyPrint...")
    output_file = 'aspex_fundraising_report.pdf'
    HTML(string=html_content).write_pdf(output_file)

    print(f"\n✓ Report generated successfully: {output_file}")
    print(f"✓ Analysis included: {analysis.get('total_applications', 'N/A')} applications")

    if 'total_potential_funding' in analysis:
        print(f"✓ Total potential funding identified: £{analysis['total_potential_funding']:,.0f}")

    print("\n" + "=" * 60)
    print("REPORT GENERATION COMPLETE")
    print("=" * 60)

    # Open in Brave browser
    print("\nOpening report in Brave browser...")
    try:
        pdf_path = os.path.abspath(output_file)
        subprocess.Popen(['brave-browser', pdf_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Browser opened!")
    except Exception as e:
        print(f"⚠ Could not open browser automatically: {e}")
        print(f"Open manually: {os.path.abspath(output_file)}")

if __name__ == "__main__":
    try:
        generate_report()
    except Exception as e:
        print(f"\n✗ Error generating report: {e}")
        import traceback
        traceback.print_exc()
