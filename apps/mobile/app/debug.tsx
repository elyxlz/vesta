import { Share } from "react-native";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { Screen } from "@/components/layout/Screen";
import { FormRow, FormSection } from "@/components/ui/Form";
import { useRoster } from "@/session/RosterProvider";

export default function DebugScreen() {
  const roster = useRoster();
  const diagnostics = [
    `App: ${Constants.expoConfig?.version ?? "unknown"}`,
    `Gateway: ${roster.gatewayVersion ?? "unknown"}`,
    `Reachable: ${String(roster.reachable)}`,
    `Agents: ${roster.agents.length}`,
    `Device: ${Device.modelName ?? "unknown"}`,
    `OS: ${Device.osName ?? "unknown"} ${Device.osVersion ?? ""}`,
  ].join("\n");

  return (
    <Screen>
      <FormSection title="Application">
        <FormRow label="App version" value={Constants.expoConfig?.version ?? "unknown"} />
        <FormRow label="Runtime" value={Constants.executionEnvironment} />
        <FormRow label="Device" value={Device.modelName ?? "unknown"} />
        <FormRow label="Operating system" value={`${Device.osName ?? "unknown"} ${Device.osVersion ?? ""}`} />
      </FormSection>
      <FormSection title="Gateway">
        <FormRow label="Reachable" value={roster.reachable ? "yes" : "no"} />
        <FormRow label="Version" value={roster.gatewayVersion ?? "unknown"} />
        <FormRow label="Agents" value={String(roster.agents.length)} />
      </FormSection>
      <FormSection>
        <FormRow
          label="Share diagnostics"
          icon="share-outline"
          onPress={() => void Share.share({ message: diagnostics })}
        />
      </FormSection>
    </Screen>
  );
}
