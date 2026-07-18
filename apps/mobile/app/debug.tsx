import { Share } from "react-native";
import Constants from "expo-constants";
import * as Device from "expo-device";
import { Screen } from "@/components/layout/Screen";
import { FormRow, FormSection } from "@/components/ui/Form";
import { useSession } from "@/session/SessionProvider";

export default function DebugScreen() {
  const session = useSession();
  const diagnostics = [
    `App: ${Constants.expoConfig?.version ?? "unknown"}`,
    `Gateway: ${session.version?.version ?? "unknown"}`,
    `API compatibility: ${session.version?.api_compat ?? "unknown"}`,
    `Reachable: ${String(session.reachable)}`,
    `Agents: ${session.agents.length}`,
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
        <FormRow label="Reachable" value={session.reachable ? "yes" : "no"} />
        <FormRow label="Version" value={session.version?.version ?? "unknown"} />
        <FormRow label="API compatibility" value={session.version?.api_compat ?? "unknown"} />
        <FormRow label="Agents" value={String(session.agents.length)} />
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
