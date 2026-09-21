"""Render the app icon, the live agent orb on a warm cream tile, for every app.

Reproduces the orb the apps render on the home page and agent cards (the
diagonal gradient sphere with a soft highlight, from AgentOrb / the shared orb
design tokens) and centers it on a cream tile. One geometry, three outputs:

- apps/desktop/build/icon.png: the tile as a squircle on Apple's macOS icon
  grid (824 content on a 1024 canvas, transparent surround); electron-builder
  derives the platform .icns/.ico from it at build time.
- apps/mobile/assets/app-icon.png: the tile full-bleed and opaque; iOS masks
  the 1024 master itself, and Android uses it for pre-adaptive launchers.
- apps/mobile/assets/adaptive-icon.png: the orb alone on a transparent 1024
  canvas, laid out on Android's adaptive-icon grid (the 72 of 108 the
  launcher shows) so it lands inside the safe zone under every mask shape;
  the tile color is the adaptive icon's backgroundColor in app.config.ts.

Colors come from the token pipeline: the orb from design/tokens.json (the
"thinking" gold state) and the tile from the generated native config, so a
recolor reaches every icon on the next run.

Run from the repo root:  uv run --with pillow --with numpy scripts/make-icons.py
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_ICON = REPO_ROOT / "apps" / "desktop" / "build" / "icon.png"
MOBILE_ASSETS = REPO_ROOT / "apps" / "mobile" / "assets"
IOS_ICON = MOBILE_ASSETS / "app-icon.png"
ANDROID_FOREGROUND = MOBILE_ASSETS / "adaptive-icon.png"
TOKENS = REPO_ROOT / "design" / "tokens.json"
NATIVE_CONFIG = REPO_ROOT / "apps" / "mobile" / "src" / "theme" / "native-config.generated.json"

MASTER = 1024  # master icon size on every platform
SS = 2  # supersample while drawing, then downscale for clean edges
CANVAS = MASTER * SS
CENTER = CANVAS / 2.0

# Apple icon grid: 824 content area centered on 1024 -> 100px margin each side.
MAC_TILE = round(824 * CANVAS / MASTER)
SQUIRCLE_N = 5.0  # superellipse exponent; ~5 matches the macOS corner
# Android adaptive grid: the launcher shows the center 72dp of a 108dp layer.
ANDROID_TILE = round(72 / 108 * CANVAS)

TRANSPARENT = (0, 0, 0, 0)

# The orb colors come straight from the canonical token source (the "thinking"
# gold state), so an orb recolor reaches the icon on the next run; the geometry
# below hand-mirrors AgentOrb / the shared orb model.
_ORB_HEX = json.loads(TOKENS.read_text())["orb"]["thinking"]
ORB_COLORS = tuple(tuple(int(hex_color[i : i + 2], 16) for i in (1, 3, 5)) for hex_color in _ORB_HEX)
_TILE_HEX = json.loads(NATIVE_CONFIG.read_text())["iconBackground"]
TILE_COLOR = (*(int(_TILE_HEX[i : i + 2], 16) for i in (1, 3, 5)), 255)
GRADIENT_START = (0.15, 0.0)  # LinearGradient start, in orb-normalized coords
GRADIENT_END = (0.9, 1.0)
ORB_FLATTEN = 0.35  # 0 = full spherical gradient, 1 = flat mid tone
ORB_SCALE = 0.8  # orb diameter as a fraction of the tile side
ORB_RISE = 0.015  # nudge the orb above optical center, as a fraction of the tile side

# Glossy highlight, mirroring AgentOrb's white oval (fractions of the orb size).
HIGHLIGHT_CENTER = (0.39, 0.28)
HIGHLIGHT_HALF = (0.21, 0.12)
HIGHLIGHT_ANGLE_DEG = -24.0
HIGHLIGHT_ALPHA = 0.24

SHADOW_MAX_ALPHA = 60  # colored contact shadow under the orb


def _squircle_mask(side: int) -> Image.Image:
    """A filled superellipse of the given side, centered, as an L-mode mask."""
    half = side / 2.0
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


def _paint_shadow(base: Image.Image, orb_center_y: float, radius: float) -> None:
    """A soft, orb-tinted contact shadow under the orb, painted onto the base in place."""
    shadow = Image.new("L", (CANVAS, CANVAS), 0)
    shadow_cy = orb_center_y + radius * 0.9
    rx, ry = radius * 0.86, radius * 0.3
    ImageDraw.Draw(shadow).ellipse(
        [CENTER - rx, shadow_cy - ry, CENTER + rx, shadow_cy + ry],
        fill=SHADOW_MAX_ALPHA,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius * 0.28))
    tint = Image.new("RGBA", (CANVAS, CANVAS), (*ORB_COLORS[2], 255))
    base.paste(tint, (0, 0), shadow)


def _compose(tile: int, fill: tuple[int, int, int, int]) -> Image.Image:
    """The orb and its shadow laid out for a tile of the given side, on a full canvas of `fill`."""
    diameter = round(tile * ORB_SCALE)
    orb_center_y = CENTER - round(tile * ORB_RISE)
    base = Image.new("RGBA", (CANVAS, CANVAS), fill)
    _paint_shadow(base, orb_center_y, diameter / 2.0)
    top_left = (round(CENTER - diameter / 2), round(orb_center_y - diameter / 2))
    base.alpha_composite(_render_orb(diameter), dest=top_left)
    return base


def _master(image: Image.Image) -> Image.Image:
    return image.resize((MASTER, MASTER), Image.Resampling.LANCZOS)


def main() -> None:
    desktop = _compose(MAC_TILE, TILE_COLOR)
    desktop.putalpha(_squircle_mask(MAC_TILE))
    outputs = {
        DESKTOP_ICON: _master(desktop),
        IOS_ICON: _master(_compose(CANVAS, TILE_COLOR)).convert("RGB"),
        ANDROID_FOREGROUND: _master(_compose(ANDROID_TILE, TRANSPARENT)),
    }
    for path, image in outputs.items():
        path.parent.mkdir(exist_ok=True)
        image.save(path)
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
