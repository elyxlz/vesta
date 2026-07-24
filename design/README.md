# Vesta design tokens

[`tokens.json`](./tokens.json) is the single source of truth for Vesta's semantic colors, type families, radii, and core spacing.

After changing it, run:

```sh
python3 scripts/sync-design-tokens.py
bash scripts/sync-dashboard.sh
```

The generator produces:

- `apps/web/src/design-tokens.css` and `design-tokens.ts` for the web app and Electron desktop app
- `apps/mobile/src/theme/generated.ts` with deterministic sRGB values and native font names for React Native
- `apps/mobile/src/theme/native-config.generated.json` for Expo's pre-Metro native configuration
- `agent/skills/dashboard/app/src/design-tokens.css` through the existing dashboard sync

Do not edit generated files directly. CI runs the generator in check mode and then verifies the dashboard mirror, so token drift fails before merge.
