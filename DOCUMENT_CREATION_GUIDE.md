# CREATING PROFESSIONAL DOCUMENTS & VISUALIZATIONS

## Making Pretty Things - Core Patterns

**Tech Stack:**
- WeasyPrint for PDF (HTML/CSS → PDF)
- Jinja2 for HTML templating
- matplotlib + seaborn for charts
- Always use `uv run` with inline dependencies

**Design Basics:**
- Fonts: Helvetica 11pt body, 24pt titles
- Margins: 2-3cm for A4
- Colors: Use teal #2a9d8f as accent, #f8f9fa for backgrounds
- Charts: 85% width, not full page
- Spacing: Use plt.subplots_adjust(bottom=0.30) to avoid label overlap

**Color Palette (PESTEL style):**
- Political: #e76f51, Economic: #2a9d8f, Social: #e9c46a
- Tech: #4d96ff, Environment: #6bcf7f, Legal: #9d4edd

**Key Code Pattern:**
```python
#!/usr/bin/env python3
# /// script
# dependencies = ["weasyprint", "jinja2", "matplotlib"]
# ///
# 1. Define data structures
# 2. Create HTML_TEMPLATE with Jinja2
# 3. Render template and convert to PDF/PNG
# 4. Open in browser automatically
```

**Writing Style:**
- Third-person neutral
- No emojis in professional docs
- Bullet points for lists/recommendations
