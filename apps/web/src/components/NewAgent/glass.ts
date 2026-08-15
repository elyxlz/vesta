// One frosted fill shared by every onboarding surface; shape splits by size.
// Small controls (input, buttons) are pills; large surfaces (tiles) keep
// corner-shape squircles, which Chromium renders and other engines round.
const frost =
  "border border-border/50 bg-input/30 backdrop-blur-xl " +
  "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.06),0_8px_32px_rgb(0_0_0/0.08)]";

export const glassSurface = `rounded-[3rem] [corner-shape:squircle] ${frost}`;

export const glassPill = `rounded-full ${frost}`;

export const glassHover =
  "transition-all hover:-translate-y-0.5 hover:border-border/80 hover:bg-input/50 hover:shadow-lg";

export const glassSelected =
  "border-primary/60 bg-primary/10 ring-2 ring-primary/20";

export const glassAction =
  "rounded-full bg-primary/85 backdrop-blur-xl hover:bg-primary/95 " +
  "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.15),0_8px_24px_rgb(0_0_0/0.10)]";
