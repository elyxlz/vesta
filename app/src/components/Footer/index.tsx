export function Footer() {
  return (
    <div className="flex items-center justify-center shrink-0 select-none absolute bottom-3 left-0 right-0">
      <span className="text-xs font-light text-muted-foreground pointer-events-none">
        v{__APP_VERSION__}
      </span>
    </div>
  );
}
