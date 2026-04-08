export function Footer() {
  return (
    <div className="flex items-center justify-center h-11 shrink-0 select-none bg-background">
      <span className="text-xs text-muted-foreground pointer-events-none">
        v{__APP_VERSION__}
      </span>
    </div>
  );
}
