# ASPEX Fundraising Report - Analysis & Fix Plan

**Date:** October 28, 2025
**Status:** Issues Identified - Ready to Fix

---

## 🐛 CRITICAL DATA ISSUES FOUND

### Issue 1: Headers Mixed with Data
**Problem:** CSV parsing includes header rows as data
```
- "Project name" appears as a project (it's a header)
- "Amount to be applied for" appears as an amount (it's a header)
- "Progress (Scoping/ writing/ submitted)" counted as progress status
```
**Impact:** Inflates row count, pollutes charts with meaningless entries

### Issue 2: Inconsistent Project Names
**Problem:** Same project counted multiple times due to formatting
```
Current data shows:
- "Generate" (count: 2)
- "Generate " (count: 1) - note trailing space
- "Generate?" (count: 1)

Should be: "Generate" (count: 4)
```
**Impact:** Chart shows duplicate categories, makes analysis confusing

### Issue 3: Broken Amount Parsing
**Problem:** Regex only catches simple formats, misses most amounts

```python
Current regex: r'£([\d,]+)K?'

WORKS:
✓ "Up to £40K" → 40000
✓ "£50K" → 50000

FAILS:
✗ "10% of total annual turnover i.e. Max £35K" → extracts 10, not 35000
✗ "under £7,500" → extracts 7, not 7500
✗ "TBC" → should be None, currently fails
✗ "Between £10-25K" → only gets first number
```

**Impact:** Only 5 amounts parsed out of potentially 15-20, total funding wildly inaccurate

### Issue 4: Only 5 Amounts Showing
**Problem:** Chart says "5 opportunities" but there are 34 applications

**Actual data:**
- 34 total applications
- Only 5 have successfully parsed amounts
- Many have amounts in text form not being captured

**Impact:** "Grant Size Distribution" chart is misleading, looks like sparse data

### Issue 5: Text Way Too Long
**Problem:** Report is ~1200 words, reads like academic paper not blog

**Current word counts by section:**
- Intro: ~80 words
- Pipeline: ~60 words
- Application Focus: ~70 words
- Grant Distribution: ~75 words
- Funder Landscape: ~50 words
- Key Findings: ~550 words (TOO LONG)
- Recommendations: ~350 words (TOO LONG)

**Target:** 600 words total (50% reduction)

---

## ✅ WORK COMPLETED

### Phase 1: Technology Migration ✓
- [x] Switched from matplotlib PdfPages to WeasyPrint
- [x] Implemented HTML/CSS template system
- [x] Added Jinja2 templating
- [x] Charts converted to base64 embedded images

### Phase 2: Layout & Design ✓
- [x] Professional margins (2.5cm/3cm)
- [x] Clean typography (Helvetica 11pt, 1.6 line height)
- [x] Charts at 85% width (not full page)
- [x] Proper spacing between sections
- [x] Color-coded headers with teal accents

### Phase 3: Tone & Language ✓
- [x] Removed all emojis
- [x] Removed "we/you/I" pronouns
- [x] Third-person neutral voice throughout
- [x] No cringy motivational phrases
- [x] Professional but accessible language

---

## 🔧 FIXES REQUIRED

### Priority 1: Data Quality (CRITICAL)

**A. Better CSV Cleaning**
```python
# Add filtering for header rows
def load_and_clean_pipeline_data(filepath):
    # ... existing code ...

    # Remove header rows that snuck through
    df_clean = df_clean[~df_clean['Funder'].isin([
        'Applying to',
        'Fundraising / Future Projects IN PROGRESS'
    ])]
    df_clean = df_clean[~df_clean['Project'].isin([
        'Project name',
        'Project dates'
    ])]
    df_clean = df_clean[~df_clean['Progress'].str.contains(
        'Progress \\(',
        regex=True,
        na=False
    )]
```

**B. Normalize Project Names**
```python
# Clean up project names
df_clean['Project'] = df_clean['Project'].str.strip()  # Remove spaces
df_clean['Project'] = df_clean['Project'].str.replace('?', '')  # Remove ?
df_clean['Project'] = df_clean['Project'].fillna('Unspecified')
```

**C. Improved Amount Parsing**
```python
def extract_amount(amount_str):
    """Extract funding amount from various text formats"""
    if pd.isna(amount_str):
        return None

    amount_str = str(amount_str).upper()

    # Handle TBC, N/A
    if 'TBC' in amount_str or 'N/A' in amount_str:
        return None

    # Try patterns in order of specificity
    patterns = [
        r'MAX\s*£([\d,]+)K?',           # "Max £35K"
        r'UNDER\s*£([\d,]+)',           # "under £7,500"
        r'UP TO\s*£([\d,]+)K?',         # "Up to £40K"
        r'BETWEEN\s*£([\d,]+)',         # "Between £10-25K"
        r'£([\d,]+)K',                   # "£50K"
        r'£([\d,]+)',                    # "£7,500"
    ]

    for pattern in patterns:
        match = re.search(pattern, amount_str)
        if match:
            amount = float(match.group(1).replace(',', ''))
            # If pattern ends with K and number < 1000, multiply
            if 'K' in pattern and amount < 1000:
                amount *= 1000
            return amount

    return None
```

### Priority 2: Text Reduction (HIGH)

**Goal:** Cut from ~1200 words to ~600 words

**Intro Section** (80 words → 30 words)
```
CURRENT:
"This analysis examines ASPEX's current fundraising pipeline, funding
distribution patterns, and the broader 2025 funding landscape. The UK
arts sector faces increased competition for trust and foundation funding,
with 67% of local authorities reducing arts budgets. Despite these
challenges, opportunities remain for organizations with clear mission
alignment and strategic positioning."

NEW:
"This analysis examines 34 funding applications representing £XXX,XXX
in potential funding. The 2025 UK arts landscape is competitive, with
local authority cuts driving organizations toward trusts and foundations."
```

**Section Text** (60-75 words → 25-35 words each)

Current Pipeline:
```
OLD: "Applications are distributed across multiple stages, from initial
scoping through to submission. The majority remain in early phases,
indicating ongoing development work. The pipeline includes both core
funding applications (operational sustainability) and project-specific
opportunities (creative programming, community engagement)."

NEW: "Most applications are in early scoping stages. The pipeline targets
both core operational funding and project-specific opportunities for
creative programming and community engagement."
```

**Key Findings** (550 words → 200 words)
- Merge "2025 Funding Environment" + "Strategic Positioning"
- Keep only essential stats (67% cuts, 40% sustainability increase)
- Remove redundant explanations

**Recommendations** (350 words → 150 words)
- Combine Immediate + Short-term → "Next 6 Months"
- Bullet point format instead of paragraphs
- Remove explanatory text, keep actions only

### Priority 3: Chart Improvements (MEDIUM)

**A. Limit Categories**
```python
def create_category_chart(analysis):
    # Show top 8 instead of all 13
    project_data = pd.Series(analysis['by_project']).head(8)
    # ... rest of code
```

**B. Add Data Quality Note**
```python
def create_amounts_chart(analysis):
    # ... existing code ...

    # Add note about data completeness
    note = f"Based on {len(amounts)} of {total_apps} applications with parseable amounts"
    ax.text(0.5, -0.15, note, transform=ax.transAxes,
            ha='center', fontsize=8, style='italic', color='#666')
```

---

## 📊 EXPECTED OUTCOMES

**After Fixes:**
- ✓ Clean data: no headers in results, normalized names
- ✓ Accurate totals: 15-20 parsed amounts instead of 5
- ✓ Correct funding total: likely £200K-300K not £127K
- ✓ Clear charts: top categories only, no duplicates
- ✓ Concise text: 600 words, 3-4 pages instead of 5
- ✓ Professional result ready for submission

---

## 🎯 IMPLEMENTATION ORDER

1. **Fix data parsing** (30 min)
   - Header filtering
   - Project name normalization
   - Improved amount extraction

2. **Test data accuracy** (10 min)
   - Run analysis on cleaned data
   - Verify counts and totals
   - Check for any remaining issues

3. **Cut text by 50%** (20 min)
   - Intro: 80 → 30 words
   - Sections: 60-75 → 25-35 words each
   - Key Findings: 550 → 200 words
   - Recommendations: 350 → 150 words

4. **Refine charts** (10 min)
   - Top 8 categories only
   - Add data quality notes
   - Test visual balance

5. **Final review** (10 min)
   - Generate new PDF
   - Check page count (should be 3-4 pages)
   - Verify all bugs fixed

**Total Time:** ~80 minutes

---

## 📝 NOTES

- Keep backup of current version (`generate_report.py.bak` already exists)
- Test regex patterns individually before implementing
- Validate total funding amount makes sense for 34 applications
- Consider adding a "Data Quality" section if many amounts still missing
- Blog style = shorter paragraphs, punchier language, less academic
