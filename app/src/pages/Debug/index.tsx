import { Orb } from "@/components/Orb";
import {
  orbColors,
  type OrbVisualState,
} from "@/components/Orb/styles";

const states: OrbVisualState[] = [
  "alive",
  "thinking",
  "booting",
  "authenticating",
  "starting",
  "stopping",
  "deleting",
  "dead",
  "loading",
];

export function Debug() {
  return (
    <div className="flex flex-1 flex-col gap-8 overflow-y-auto p-8">
      <h1 className="text-lg font-medium text-foreground">orb states</h1>
      <div className="grid grid-cols-3 gap-8 max-sm:grid-cols-2">
        {states.map((state) => {
          const [c1, c2, c3] = orbColors[state];
          return (
            <div key={state} className="flex flex-col items-center gap-3">
              <div className="h-[120px] w-[120px]">
                <Orb state={state} size={120} />
              </div>
              <span className="text-sm font-medium text-foreground">
                {state}
              </span>
              <div className="flex gap-1.5">
                {[c1, c2, c3].map((c) => (
                  <div
                    key={c}
                    className="h-4 w-4 rounded-full border border-border"
                    style={{ backgroundColor: c }}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
