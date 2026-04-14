export function Footer() {
  return (
    <div className="flex items-center justify-center shrink-0 select-none absolute bottom-3 left-0 right-0">
      <span className="pointer-events-none rounded px-1 py-px text-[9px] leading-none text-muted-foreground">
        v{__APP_VERSION__}
      </span>
    </div>
  );
}
