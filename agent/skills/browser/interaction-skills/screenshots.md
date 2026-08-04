# Screenshots

Screenshots are costly in context: prefer `--webp` (much smaller than PNG) and `--region` to
clip to the part that matters. Use PNG only when you need lossless output (e.g. pixel-diffing UI
state). Camoufox captures PNG and JPEG natively; `--webp` is encoded as JPEG.

```bash
browser screenshot [--path PATH] [--full-page] [--webp] [--region X,Y,W,H] [--quality N]
```

In Python stdin mode: `screenshot(path, full_page=..., image_format=..., region=(x, y, w, h),
quality=...)`.
