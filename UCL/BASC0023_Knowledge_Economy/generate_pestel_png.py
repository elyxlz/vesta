#!/usr/bin/env python3
# /// script
# dependencies = [
#   "matplotlib",
# ]
# ///
"""
BASc Employability PESTEL Analysis Generator - PNG Version
"""

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
import os

# PESTEL data
pestel_data = {
    "Political": [
        "Graduate visa policies (2-year post-study work visa)",
        "Higher education funding cuts",
        "Brexit impact on EU student employment",
    ],
    "Economic": [
        "Economic recession reducing graduate job openings",
        "High cost of living in London affecting job choice",
        "Startup ecosystem funding drought",
    ],
    "Social": [
        'Employer bias against "generalist" degrees',
        "Limited alumni network (new program)",
        "Class privilege in unpaid internship culture",
    ],
    "Technological": [
        "AI automating entry-level jobs",
        "Remote work creating global competition",
        "Digital skills gap in traditional industries",
    ],
    "Environmental": [
        "Green economy creating new job types",
        "ESG requirements creating interdisciplinary roles",
        "Climate change forcing industry transitions",
    ],
    "Legal": [
        "Employment law changes (IR35, gig economy)",
        "Professional qualification requirements",
        "Data protection laws affecting recruitment processes",
    ],
}

# Color scheme for each category
colors = {
    "Political": "#e76f51",  # coral red
    "Economic": "#2a9d8f",  # teal
    "Social": "#e9c46a",  # yellow
    "Technological": "#4d96ff",  # blue
    "Environmental": "#6bcf7f",  # green
    "Legal": "#9d4edd",  # purple
}


def create_pestel_diagram():
    """Create PESTEL diagram as PNG"""
    print("=" * 60)
    print("PESTEL ANALYSIS DIAGRAM GENERATOR (PNG)")
    print("=" * 60)
    print()

    print("Creating PESTEL diagram...")

    # Create figure with white background
    fig = plt.figure(figsize=(11, 14), facecolor="white")
    ax = fig.add_subplot(111)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 14)
    ax.axis("off")

    # Title
    ax.text(5, 13.5, "PESTEL ANALYSIS", ha="center", va="top", fontsize=24, fontweight="bold", color="#1a1a1a")
    ax.text(
        5, 13.0, "BASc Employability Problem - External Environment Factors", ha="center", va="top", fontsize=12, color="#666", style="italic"
    )

    # Draw horizontal line under title
    ax.plot([1, 9], [12.7, 12.7], color="#2a9d8f", linewidth=3)

    # Grid layout: 2 columns, 3 rows
    categories = ["Political", "Economic", "Social", "Technological", "Environmental", "Legal"]
    positions = [
        (0.5, 8.5, 4.5, 3.8),  # Political (left, top)
        (5.5, 8.5, 4.5, 3.8),  # Economic (right, top)
        (0.5, 4.5, 4.5, 3.8),  # Social (left, middle)
        (5.5, 4.5, 4.5, 3.8),  # Technological (right, middle)
        (0.5, 0.5, 4.5, 3.8),  # Environmental (left, bottom)
        (5.5, 0.5, 4.5, 3.8),  # Legal (right, bottom)
    ]

    for category, (x, y, width, height) in zip(categories, positions):
        color = colors[category]

        # Draw box with colored left border
        box = FancyBboxPatch((x, y), width, height, boxstyle="round,pad=0.05", edgecolor=color, facecolor="#f8f9fa", linewidth=2, zorder=1)
        ax.add_patch(box)

        # Add thick left border
        ax.plot([x, x], [y, y + height], color=color, linewidth=8, solid_capstyle="round")

        # Category title
        ax.text(x + 0.3, y + height - 0.3, category.upper(), fontsize=13, fontweight="bold", color=color, va="top")

        # Bullet points
        items = pestel_data[category]
        y_offset = y + height - 0.8
        for item in items:
            # Word wrap for long text
            words = item.split()
            lines = []
            current_line = []
            current_length = 0
            max_length = 45  # characters per line

            for word in words:
                if current_length + len(word) + 1 <= max_length:
                    current_line.append(word)
                    current_length += len(word) + 1
                else:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_length = len(word)
            if current_line:
                lines.append(" ".join(current_line))

            # Draw bullet point
            ax.plot(x + 0.25, y_offset, "o", color="#333", markersize=3)

            # Draw text (possibly multiple lines)
            for i, line in enumerate(lines):
                ax.text(x + 0.4, y_offset - (i * 0.25), line, fontsize=9, va="top", color="#333")

            y_offset -= 0.25 * len(lines) + 0.15

    # Footer
    ax.text(
        5, 0.2, "BASc Employability PESTEL Analysis • UCL Knowledge Economy • October 2025", ha="center", va="bottom", fontsize=8, color="#666"
    )

    # Save as PNG
    output_file = "basc_employability_pestel.png"
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close()

    print(f"\n✓ PESTEL diagram generated successfully: {output_file}")
    print("✓ Resolution: 300 DPI")
    print("\n" + "=" * 60)
    print("GENERATION COMPLETE")
    print("=" * 60)

    # Open in browser
    print("\nOpening PNG in image viewer...")
    try:
        img_path = os.path.abspath(output_file)
        import subprocess

        subprocess.Popen(["xdg-open", img_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✓ Image viewer opened!")
    except Exception as e:
        print(f"⚠ Could not open image viewer automatically: {e}")
        print(f"Open manually: {os.path.abspath(output_file)}")


if __name__ == "__main__":
    try:
        create_pestel_diagram()
    except Exception as e:
        print(f"\n✗ Error generating PESTEL diagram: {e}")
        import traceback

        traceback.print_exc()
