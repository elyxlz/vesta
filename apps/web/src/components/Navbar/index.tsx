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
      data-drag-region
      className="absolute top-0 left-0 right-0 z-[99999] flex flex-col shrink-0 min-h-0 select-none overflow-visible px-2.5"
      style={{
        paddingTop: "var(--safe-area-pt)",
        paddingBottom: "var(--navbar-pb)",
      }}
    >
      <div
        data-drag-region
        className="grid grid-cols-[1fr_auto_1fr] items-center"
      >
        <div
          data-drag-region
          className="flex items-center gap-2 justify-self-start"
          style={{ paddingLeft: "var(--titlebar-inset-left, 0px)" }}
        >
          {leading}
        </div>

        <div data-drag-region className="flex items-center justify-self-center">
          {center}
        </div>

        <div
          data-drag-region
          className="flex items-center gap-2 justify-self-end"
        >
          {trailing}
          <WindowControls />
        </div>
      </div>
    </div>
  );
}
