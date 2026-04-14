export function LogoText({ className }: { className?: string }) {
  return (
    <span
      data-tauri-drag-region
      className={`text-3xl font-serif font-medium tracking-tight ${className ?? ""}`}
    >
      Vesta
    </span>
  );
}
