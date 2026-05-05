import { orbColors, type OrbVisualState } from "@/components/Orb/styles";

const DEFAULT_HREF = "/favicon.png?v=2";
const FAVICON_SIZE = 64;
const CORNER_RADIUS = 12;
const ORB_MARGIN = 5;
const BG_COLOR = "#ffffff";
const DOT_COLOR = "#d33a3f";
const DOT_RADIUS = FAVICON_SIZE * 0.22;
const DOT_RING = 6;
const DOT_INSET = 2;

let currentOrb: OrbVisualState | null = null;
let unseen = false;
let defaultImg: HTMLImageElement | null = null;
let defaultImgLoaded = false;
const cache = new Map<string, string>();

function getLink(): HTMLLinkElement | null {
  if (typeof document === "undefined") return null;
  return document.querySelector<HTMLLinkElement>('link[rel="icon"]');
}

function ensureDefaultImg(): void {
  if (defaultImg) return;
  const img = new Image();
  img.src = DEFAULT_HREF;
  img.onload = () => {
    defaultImgLoaded = true;
    render();
  };
  defaultImg = img;
}

function drawBackground(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = BG_COLOR;
  ctx.beginPath();
  ctx.roundRect(0, 0, FAVICON_SIZE, FAVICON_SIZE, CORNER_RADIUS);
  ctx.fill();
}

function drawOrb(ctx: CanvasRenderingContext2D, state: OrbVisualState): void {
  const [c1, c2, c3] = orbColors[state];
  const center = FAVICON_SIZE / 2;
  const radius = center - ORB_MARGIN;
  const grad = ctx.createRadialGradient(
    center - 6,
    center - 8,
    2,
    center,
    center,
    radius,
  );
  grad.addColorStop(0, c1);
  grad.addColorStop(0.5, c2);
  grad.addColorStop(1, c3);

  ctx.fillStyle = grad;
  ctx.beginPath();
  ctx.arc(center, center, radius, 0, Math.PI * 2);
  ctx.fill();
}

function dotCenter(): [number, number] {
  return [FAVICON_SIZE - DOT_RADIUS - DOT_INSET, DOT_RADIUS + DOT_INSET];
}

function render(): void {
  const link = getLink();
  if (!link) return;

  const cacheKey = `${currentOrb ?? "default"}|${unseen ? 1 : 0}`;
  const hit = cache.get(cacheKey);
  if (hit) {
    link.href = hit;
    link.type = "image/png";
    return;
  }

  // Fast path: no orb, no badge — just the static file.
  if (!currentOrb && !unseen) {
    link.href = DEFAULT_HREF;
    link.type = "image/png";
    return;
  }

  // No orb but unseen — need the default image to draw against.
  if (!currentOrb && !defaultImgLoaded) {
    ensureDefaultImg();
    link.href = DEFAULT_HREF;
    link.type = "image/png";
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.width = FAVICON_SIZE;
  canvas.height = FAVICON_SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  if (currentOrb) {
    drawBackground(ctx);
    drawOrb(ctx, currentOrb);
  } else if (defaultImgLoaded && defaultImg) {
    ctx.drawImage(defaultImg, 0, 0, FAVICON_SIZE, FAVICON_SIZE);
  }

  if (unseen) {
    const [cx, cy] = dotCenter();

    // Punch a fully transparent ring through every layer drawn so far —
    // background, orb, default image — exposing the tab itself.
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    ctx.fillStyle = "rgba(0,0,0,1)";
    ctx.beginPath();
    ctx.arc(cx, cy, DOT_RADIUS + DOT_RING, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // Drop the dot back into the hole.
    ctx.fillStyle = DOT_COLOR;
    ctx.beginPath();
    ctx.arc(cx, cy, DOT_RADIUS, 0, Math.PI * 2);
    ctx.fill();
  }

  const url = canvas.toDataURL("image/png");
  cache.set(cacheKey, url);
  link.href = url;
  link.type = "image/png";
}

export function setFaviconForOrbState(state: OrbVisualState): void {
  currentOrb = state;
  render();
}

export function clearFaviconOrbState(): void {
  currentOrb = null;
  render();
}

export function setFaviconUnseen(on: boolean): void {
  if (unseen === on) return;
  unseen = on;
  render();
}
