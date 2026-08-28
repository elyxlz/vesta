import { schemeColors } from "@/design-tokens";
import { cn } from "@/lib/utils";

export type ThemeChoice = "system" | "light" | "dark";
type Scheme = "light" | "dark";

const OPTIONS: { value: ThemeChoice; label: string }[] = [
  { value: "system", label: "system" },
  { value: "light", label: "light" },
  { value: "dark", label: "dark" },
];

// A simplified chat frame in one scheme (background, a card with two text
// lines, the primary send pill), painted from the token palette directly so it
// shows that scheme whatever the app is currently using. Mirrors mobile's
// AppearancePreview.
function SchemeFrame({ scheme }: { scheme: Scheme }) {
  const palette = schemeColors[scheme];
  return (
    <div
      className="flex h-full w-full flex-col justify-between p-2"
      style={{ backgroundColor: palette.background }}
    >
      <div
        className="flex w-[56%] flex-col gap-[3px] rounded-[4px] p-1"
        style={{ backgroundColor: palette.card }}
      >
        <div
          className="h-[2px] rounded-full opacity-55"
          style={{ backgroundColor: palette["muted-foreground"] }}
        />
        <div
          className="h-[2px] w-[60%] rounded-full opacity-55"
          style={{ backgroundColor: palette["muted-foreground"] }}
        />
      </div>
      <div
        className="h-1.5 w-[40%] self-end rounded-full"
        style={{ backgroundColor: palette.primary }}
      />
    </div>
  );
}

// The system tile shows light above and dark below the bottom-left to
// top-right diagonal.
function AppearancePreview({ theme }: { theme: ThemeChoice }) {
  if (theme !== "system") return <SchemeFrame scheme={theme} />;
  return (
    <div className="relative h-full w-full">
      <SchemeFrame scheme="light" />
      <div
        className="absolute inset-0"
        style={{ clipPath: "polygon(0 100%, 100% 0, 100% 100%)" }}
      >
        <SchemeFrame scheme="dark" />
      </div>
    </div>
  );
}

// Three preview tiles, the tile being the selectable surface and the selection
// a ring around it, matching the mobile appearance control.
export function AppearancePicker({
  value,
  options = OPTIONS,
  onChange,
}: {
  value: ThemeChoice;
  options?: readonly { value: ThemeChoice; label: string }[];
  onChange: (value: ThemeChoice) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="appearance"
      className="flex justify-evenly gap-3 px-2 py-1"
    >
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.value)}
            className="group/tile flex w-full min-w-0 max-w-32 flex-col items-center gap-1.5 outline-none"
          >
            <span
              className={cn(
                "aspect-[5/3] w-full overflow-hidden rounded-lg ring-1 transition-[box-shadow,transform] group-focus-visible/tile:ring-2 group-focus-visible/tile:ring-ring group-active/tile:scale-[0.98]",
                selected
                  ? "ring-2 ring-primary"
                  : "ring-border group-hover/tile:ring-foreground/30",
              )}
            >
              <AppearancePreview theme={option.value} />
            </span>
            <span
              className={cn(
                "text-xs font-medium",
                selected ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {option.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
