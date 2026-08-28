export function LogoText({ className }: { className?: string }) {
  return (
    <span
      data-drag-region
      className={`text-[2.1rem] leading-none font-wordmark font-medium tracking-tight ${className ?? ""}`}
    >
      vesta
    </span>
  );
}

// The wordmark as a navbar center: one optical lift shared by every navbar, so
// the mark sits at the same height on every page.
export function NavbarLogoText() {
  return <LogoText className="-translate-y-1" />;
}
