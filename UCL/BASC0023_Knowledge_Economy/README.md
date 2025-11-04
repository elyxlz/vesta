# ASPEX Fundraising Analysis Report

**UCL BASc Knowledge Economy - Student Consultancy Project 2025**

## Overview

This project analyzes ASPEX's fundraising pipeline and funder database to produce a comprehensive PDF report with data visualizations and strategic recommendations.

## Files

- `generate_report.py` - Main Python script with inline dependencies (uses uv)
- `Arts_Funders_and_Websites.csv` - Historical funder database (434KB)
- `Fundraising_Future_Projects.csv` - Current fundraising pipeline (36KB)
- `aspex_fundraising_report.pdf` - Generated 7-page PDF report (81KB)

## Requirements

- Python 3.10+
- `uv` package manager (handles dependencies automatically)

## Usage

Run the report generator with a single command:

```bash
uv run generate_report.py
```

The script will automatically:
1. Install required dependencies (pandas, matplotlib, seaborn, numpy)
2. Load and analyze both CSV files
3. Generate visualizations
4. Create `aspex_fundraising_report.pdf`

## Report Contents

**7-Page PDF Report:**

1. **Title Page** - Report identification and date
2. **Executive Summary** - Key findings and immediate recommendations
3. **Pipeline Status Chart** - Visual breakdown of application stages
4. **Funding Categories Chart** - Applications by project type
5. **Grant Amount Distribution** - Funding range analysis
6. **Funder Type Analysis** - Database categorization by focus area
7. **Strategic Commentary** - Knowledge economy perspective and recommendations

## Key Findings

- **34 active applications** analyzed
- **£127,500 total potential funding** identified
- Focus areas: Core funding, Creative Engagement, Arts Programming
- Multi-year funding opportunities aligned with ASPEX values

## Analysis Highlights

### Current Pipeline
- Applications in progress: Esmee Fairbairn (£50K/year, 3-5 years)
- Target funders: Garfield Weston, Art Fund, Henry Moore Foundation
- Urgent deadline: November 5, 2025 (Esmee Fairbairn)

### Strategic Recommendations
1. **Immediate (0-3 months)**: Complete in-progress applications, target Austin Hope Pilkington Trust
2. **Short-term (3-6 months)**: Develop university partnerships, strengthen legacy giving
3. **Long-term (6-12 months)**: Build multi-year funding pipeline with 3-5 major funders

### 2025 Funding Context
- UK trusts/foundations overwhelmed with applications
- 67% of local authorities cutting arts funding
- Diversification critical for sustainability
- Multi-year grants available: Arts Council England, British Council

## Data Sources

- ASPEX internal fundraising database (historical data since 2012)
- Current pipeline tracker (updated October 2025)
- UK arts funding trends research (2025)
- Similar organization analysis (Arnolfini, Gasworks, Whitechapel Gallery)

## Technical Details

**Dependencies (auto-managed by uv):**
- pandas - Data analysis
- matplotlib - Charts and graphs
- seaborn - Statistical visualizations
- numpy - Numerical operations

**Script Features:**
- PEP 723 inline dependency specification
- Automated data cleaning and parsing
- Dynamic chart generation
- Professional PDF layout with reportlab

## Modifying the Report

To customize the analysis:

1. Edit `generate_report.py`
2. Modify visualization functions for different chart types
3. Update commentary in `create_commentary_page()`
4. Adjust funding range bins in Figure 3 creation
5. Re-run: `uv run generate_report.py`

## Contact

UCL Arts and Sciences BASc Programme
Module: BASC0023 - The Knowledge Economy
Client: ASPEX Portsmouth

---

*Generated: October 2025*
*Report analyzes ASPEX fundraising data with strategic recommendations based on knowledge economy principles and current UK arts funding trends.*
