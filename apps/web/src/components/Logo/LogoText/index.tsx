export function LogoText({ className }: { className?: string }) {
  return (
    <span
      data-tauri-drag-region
      className={`text-[2.1rem] leading-none font-serif font-medium tracking-tight ${className ?? ""}`}
    >
      vesta
    </span>
  );
}
