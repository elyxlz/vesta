import { useLayout } from "@/stores/use-layout";

// An eased fade beneath the (transparent) navbar so content scrolling under it
// dissolves into the background instead of hard-clipping. The alpha stops follow
// an ease-in-out curve rather than a 2-stop linear ramp, so there's no visible
// band edge. Sits above page content but below the navbar's controls (z-[99999]).
const EASED_FADE =
  "linear-gradient(to bottom," +
  " var(--background) 0%," +
  " color-mix(in oklab, var(--background) 95%, transparent) 19%," +
  " color-mix(in oklab, var(--background) 84%, transparent) 34%," +
  " color-mix(in oklab, var(--background) 68%, transparent) 47%," +
  " color-mix(in oklab, var(--background) 50%, transparent) 56.5%," +
  " color-mix(in oklab, var(--background) 32%, transparent) 65%," +
  " color-mix(in oklab, var(--background) 16%, transparent) 73%," +
  " color-mix(in oklab, var(--background) 5%, transparent) 82%," +
  " transparent 100%)";

export function NavbarScrim() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 z-40"
      style={{ height: navbarHeight * 2, background: EASED_FADE }}
    />
  );
}
