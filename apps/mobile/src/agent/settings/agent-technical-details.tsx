import { useState } from "react";
import { useAgent } from "@/agent/AgentProvider";
import { FormRow, FormSection } from "@/components/ui/Form";

export function AgentTechnicalDetails() {
  const { agent, activityState } = useAgent();
  const [expanded, setExpanded] = useState(false);

  return (
    <FormSection>
      <FormRow
        label="Technical details"
        expanded={expanded}
        onPress={() => setExpanded((value) => !value)}
      />
      {expanded ? (
        <>
          <FormRow
            label="Agent state"
            value={agent?.status.replace(/_/g, " ") ?? "unavailable"}
          />
          <FormRow label="Activity" value={activityState} />
          <FormRow
            label="Started"
            value={
              agent?.startedAt
                ? new Date(agent.startedAt).toLocaleString()
                : "not available"
            }
          />
          <FormRow
            label="Services"
            value={String(Object.keys(agent?.services ?? {}).length)}
          />
        </>
      ) : null}
    </FormSection>
  );
}
