"""Frame the app's live agent orb into the classic macOS app-icon shape.

Reproduces the orb the mobile apps render on the home page and agent cards
(the diagonal gradient sphere with a soft highlight, from AgentOrb / the shared
orb design tokens), centers it on a warm cream squircle laid out on Apple's icon
grid (824 content on a 1024 canvas), and writes build/icon.png. electron-builder
derives the platform .icns/.ico from it at build time.

Run from the desktop workspace:  npm run make-icons
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DESKTOP_DIR = Path(__file__).resolve().parent.parent
BUILD_DIR = DESKTOP_DIR / "build"
REPO_ROOT = DESKTOP_DIR.parent.parent

MASTER = 1024  # macOS master icon size
SS = 2  # supersample while drawing, then downscale for clean edges
CANVAS = MASTER * SS

# Apple icon grid: 824 content area centered on 1024 -> 100px margin each side.
MARGIN = round(100 * CANVAS / MASTER)
SIDE = CANVAS - 2 * MARGIN
CENTER = CANVAS / 2.0
SQUIRCLE_N = 5.0  # superellipse exponent; ~5 matches the macOS corner

CREAM = (250, 249, 247)  # the app background the orb sits on

# The orb colors come straight from the canonical token source (the "thinking"
# gold state), so an orb recolor reaches the icon on the next make-icons run;
# the geometry below hand-mirrors AgentOrb / the shared orb model.
_ORB_HEX = json.loads((REPO_ROOT / "design" / "tokens.json").read_text())["orb"]["thinking"]
ORB_COLORS = tuple(tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5)) for hex_color in _ORB_HEX)
GRADIENT_START = (0.15, 0.0)  # LinearGradient start, in orb-normalized coords
GRADIENT_END = (0.9, 1.0)
ORB_FLATTEN = 0.35  # 0 = full spherical gradient, 1 = flat mid tone
ORB_DIAMETER = round(SIDE * 0.8)
ORB_RISE = round(SIDE * 0.015)  # nudge the orb above optical center

# Glossy highlight, mirroring AgentOrb's white oval (fractions of the orb size).
HIGHLIGHT_CENTER = (0.39, 0.28)
HIGHLIGHT_HALF = (0.21, 0.12)
HIGHLIGHT_ANGLE_DEG = -24.0
HIGHLIGHT_ALPHA = 0.24

SHADOW_MAX_ALPHA = 60  # colored contact shadow under the orb


def _squircle_mask() -> Image.Image:
    """A filled superellipse the size of the content area, as an L-mode mask."""
    half = SIDE / 2.0
    points: list[tuple[float, float]] = []
    steps = 720
    for i in range(steps):
        theta = 2.0 * math.pi * i / steps
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        x = math.copysign(abs(cos_t) ** (2.0 / SQUIRCLE_N), cos_t)
        y = math.copysign(abs(sin_t) ** (2.0 / SQUIRCLE_N), sin_t)
        points.append((CENTER + x * half, CENTER + y * half))
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def _render_orb(diameter: int) -> Image.Image:
    """The gradient sphere with its highlight, transparent outside the circle."""
    u, v = np.meshgrid(np.linspace(0.0, 1.0, diameter), np.linspace(0.0, 1.0, diameter))

    # Diagonal 3-stop gradient projected onto the start -> end axis.
    ax, ay = GRADIENT_END[0] - GRADIENT_START[0], GRADIENT_END[1] - GRADIENT_START[1]
    t = ((u - GRADIENT_START[0]) * ax + (v - GRADIENT_START[1]) * ay) / (ax * ax + ay * ay)
    t = np.clip(t, 0.0, 1.0)
    stops = np.array([0.0, 0.5, 1.0])
    palette = np.array(ORB_COLORS, dtype=float)
    palette = palette[1] + (palette - palette[1]) * (1.0 - ORB_FLATTEN)  # compress toward mid tone
    rgb = np.stack([np.interp(t, stops, palette[:, channel]) for channel in range(3)], axis=-1)

    # White highlight: rotate pixels into the oval's local frame, then test it.
    cos_a, sin_a = math.cos(math.radians(-HIGHLIGHT_ANGLE_DEG)), math.sin(math.radians(-HIGHLIGHT_ANGLE_DEG))
    hx, hy = u - HIGHLIGHT_CENTER[0], v - HIGHLIGHT_CENTER[1]
    lx = (hx * cos_a - hy * sin_a) / HIGHLIGHT_HALF[0]
    ly = (hx * sin_a + hy * cos_a) / HIGHLIGHT_HALF[1]
    highlight = np.clip(1.0 - (lx * lx + ly * ly), 0.0, 1.0) ** 0.7 * HIGHLIGHT_ALPHA
    rgb = rgb * (1.0 - highlight[..., None]) + 255.0 * highlight[..., None]

    # Circle alpha with a soft edge.
    dist = np.sqrt((u - 0.5) ** 2 + (v - 0.5) ** 2)
    alpha = np.clip((0.5 - dist) * diameter + 0.5, 0.0, 1.0) * 255.0

    data = np.dstack([np.clip(rgb, 0, 255), alpha]).astype(np.uint8)
    return Image.fromarray(data, "RGBA")


def _cream_tile_with_shadow(orb_center_y: float) -> Image.Image:
    """Cream content tile with a soft, orb-tinted contact shadow."""
    base = Image.new("RGBA", (CANVAS, CANVAS), (*CREAM, 255))
    shadow = Image.new("L", (CANVAS, CANVAS), 0)
    radius = ORB_DIAMETER / 2.0
    shadow_cy = orb_center_y + radius * 0.9
    rx, ry = radius * 0.86, radius * 0.3
    ImageDraw.Draw(shadow).ellipse(
        [CENTER - rx, shadow_cy - ry, CENTER + rx, shadow_cy + ry],
        fill=SHADOW_MAX_ALPHA,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius * 0.28))
    tint = Image.new("RGBA", (CANVAS, CANVAS), (*ORB_COLORS[2], 255))
    base.paste(tint, (0, 0), shadow)
    return base


def _render_master() -> Image.Image:
    orb = _render_orb(ORB_DIAMETER)
    orb_center_y = CENTER - ORB_RISE
    tile = _cream_tile_with_shadow(orb_center_y)
    top_left = (round(CENTER - ORB_DIAMETER / 2), round(orb_center_y - ORB_DIAMETER / 2))
    tile.alpha_composite(orb, dest=top_left)
    tile.putalpha(_squircle_mask())
    return tile.resize((MASTER, MASTER), Image.Resampling.LANCZOS)


def main() -> None:
    BUILD_DIR.mkdir(exist_ok=True)
    _render_master().save(BUILD_DIR / "icon.png")
    print(f"wrote icon.png to {BUILD_DIR}")


if __name__ == "__main__":
    main()
