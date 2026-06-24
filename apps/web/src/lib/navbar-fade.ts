import type { CSSProperties } from "react";

// An eased alpha mask for a scroll container: the top fades to transparent so
// content dissolves under the (transparent) navbar and reveals the real
// background behind it — rather than painting a colored scrim on top (which
// reads as dark in dark mode). Alpha stops follow an ease-in-out curve so the
// fade has no visible linear band. Below `fade` px the mask is fully opaque, so
// the rest of the content is untouched.
export function navbarFadeMask(navbarHeight: number): CSSProperties {
  const fade = navbarHeight * 2.3;
  const stop = (fraction: number, alpha: number) =>
    `rgba(0,0,0,${alpha}) ${Math.round(fraction * fade)}px`;
  const gradient =
    "linear-gradient(to bottom," +
    [
      stop(0, 0),
      stop(0.18, 0.05),
      stop(0.27, 0.16),
      stop(0.35, 0.32),
      stop(0.435, 0.5),
      stop(0.53, 0.68),
      stop(0.66, 0.84),
      stop(0.81, 0.95),
      stop(1, 1),
    ].join(",") +
    ")";
  return { maskImage: gradient, WebkitMaskImage: gradient };
}
