import { useEffect, useState } from "react";
import { fetchAgentDefaults, type AgentDefaults } from "@/api/agent-defaults";

// Fetches the creation-time defaults vestad owns (vestad/src/defaults.rs) so the wizard
// never keeps its own copy. `undefined` until the one-shot fetch resolves; consumers render
// a loading state until then rather than falling back to a duplicated local default.
export function useAgentDefaults(): AgentDefaults | undefined {
  const [defaults, setDefaults] = useState<AgentDefaults | undefined>(
    undefined,
  );

  useEffect(() => {
    let cancelled = false;
    fetchAgentDefaults()
      .then((d) => {
        if (!cancelled) setDefaults(d);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return defaults;
}
