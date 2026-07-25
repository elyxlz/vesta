#!/usr/bin/env python3
"""Assemble captured screenshots into a single contact-sheet PNG.

Usage: contact-sheet.py <screenshots_dir> <output_png>
Exits 0 with no output file when the directory holds no screenshots, so the
CI step stays green when an earlier failure prevented any capture.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLUMNS = 3
TILE_WIDTH = 360
PADDING = 24
LABEL_HEIGHT = 34
LABEL_TEXT_OFFSET = 8
LABEL_FONT_SIZE = 16
BACKGROUND = (245, 245, 245)
LABEL_COLOR = (60, 60, 60)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: contact-sheet.py <screenshots_dir> <output_png>", file=sys.stderr)
        return 2
    screenshots_dir = Path(sys.argv[1])
    output = Path(sys.argv[2])
    shots = sorted(screenshots_dir.glob("*.png"))
    if not shots:
        print("no screenshots found; skipping contact sheet", file=sys.stderr)
        return 0

    tiles: list[tuple[str, Image.Image]] = []
    for shot in shots:
        image = Image.open(shot)
        height = round(image.height * TILE_WIDTH / image.width)
        tiles.append((shot.stem, image.resize((TILE_WIDTH, height))))

    tile_height = max(image.height for _, image in tiles)
    columns = min(COLUMNS, len(tiles))
    rows = -(-len(tiles) // columns)
    cell_width = TILE_WIDTH + PADDING
    cell_height = tile_height + LABEL_HEIGHT + PADDING
    sheet = Image.new("RGB", (columns * cell_width + PADDING, rows * cell_height + PADDING), BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=LABEL_FONT_SIZE)

    for index, (label, image) in enumerate(tiles):
        left = PADDING + (index % columns) * cell_width
        top = PADDING + (index // columns) * cell_height
        sheet.paste(image, (left, top))
        draw.text((left, top + tile_height + LABEL_TEXT_OFFSET), label, fill=LABEL_COLOR, font=font)

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)
    print(f"contact sheet written to {output} ({len(tiles)} screenshots)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
