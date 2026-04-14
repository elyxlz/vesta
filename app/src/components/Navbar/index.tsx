import { useMeasuredHeight } from "@/hooks/use-measured-height";
import { useLayout } from "@/stores/use-layout";
import { WindowControls } from "@/components/WindowControls";

interface NavbarProps {
  leading?: React.ReactNode;
  center?: React.ReactNode;
  trailing?: React.ReactNode;
}

export function Navbar({ leading, center, trailing }: NavbarProps) {
  const setNavbarHeight = useLayout((s) => s.setNavbarHeight);
  const measureRef = useMeasuredHeight(setNavbarHeight);

  return (
    <div
      ref={measureRef}
      data-tauri-drag-region
      className="absolute top-0 left-0 right-0 z-[99999] flex flex-col shrink-0 min-h-0 select-none overflow-visible px-3 pb-1 sm:pb-3.5"
      style={{
        paddingTop:
          "calc(var(--titlebar-pt, 0.5rem) + var(--safe-area-pt, 0.5rem))",
      }}
    >
      <div
        data-tauri-drag-region
        className="relative flex flex-row items-center justify-between"
      >
        <div data-tauri-drag-region className="flex flex-1 items-center gap-2">
          {leading}
        </div>

        {center && (
          <div
            className="absolute left-1/2 top-0 bottom-0 z-[100001] flex -translate-x-1/2 items-start justify-center overflow-visible pointer-events-none"
            style={{ marginTop: "var(--titlebar-center-mt, 0px)" }}
          >
            <div className="pointer-events-auto">{center}</div>
          </div>
        )}

        <div data-tauri-drag-region className="flex items-center gap-2">
          {trailing}
          <WindowControls />
        </div>
      </div>
    </div>
  );
}
