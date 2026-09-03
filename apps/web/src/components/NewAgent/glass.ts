// One translucent fill shared by every onboarding surface. glassFrost carries
// only the inner top highlight, so cards stacked tightly (model rows) don't pool
// each other's drop shadow. Large or isolated surfaces add the ambient lift.
const fill = "border border-border/50 bg-input/60";
const inset = "inset_0_1px_0_0_rgb(255_255_255/0.06)";

export const glassFrost = `${fill} shadow-[${inset}]`;

const glassRaised = `${fill} shadow-[${inset},0_8px_32px_rgb(0_0_0/0.08)]`;

export const glassSurface = `rounded-[3rem] [corner-shape:squircle] ${glassRaised}`;

export const glassPill = `rounded-full ${glassRaised}`;

export const glassHover =
  "transition-all hover:-translate-y-0.5 hover:border-border/80 hover:bg-input/50 hover:shadow-lg";

export const glassSelected =
  "border-primary/60 bg-primary/10 ring-2 ring-primary/20";

export const glassAction =
  "rounded-full bg-primary/95 hover:bg-primary " +
  "shadow-[inset_0_1px_0_0_rgb(255_255_255/0.15),0_8px_24px_rgb(0_0_0/0.10)]";
