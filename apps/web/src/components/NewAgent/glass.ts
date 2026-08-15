// One frosted recipe for every onboarding surface. corner-shape renders true
// squircles on Chromium; other engines fall back to the plain radius.
export const glassSurface =
  "rounded-3xl [corner-shape:squircle] border border-border/50 bg-input/30 backdrop-blur-xl " +
  "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.06),0_8px_32px_rgb(0_0_0/0.08)]";

export const glassHover =
  "transition-all hover:-translate-y-0.5 hover:border-border/80 hover:bg-input/50 hover:shadow-lg";

export const glassSelected =
  "border-primary/60 bg-primary/10 ring-2 ring-primary/20";

export const glassAction =
  "rounded-2xl [corner-shape:squircle] bg-primary/85 backdrop-blur-xl hover:bg-primary/95 " +
  "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.15),0_8px_24px_rgb(0_0_0/0.10)]";
