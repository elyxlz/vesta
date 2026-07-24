import { FormSection, SwitchRow } from "@/components/ui/Form";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function AgentPagesSettingsSection() {
  const preferences = usePreferences();

  return (
    <FormSection title="Agent pages">
      <SwitchRow
        label="Notifications page"
        detail="Add notification history to the agent swipe pages."
        value={preferences.showNotificationsPage}
        onValueChange={(value) =>
          void preferences.update({ showNotificationsPage: value })
        }
      />
      <SwitchRow
        label="Logs page"
        detail="Add live output to the agent swipe pages."
        value={preferences.showLogsPage}
        onValueChange={(value) =>
          void preferences.update({ showLogsPage: value })
        }
      />
    </FormSection>
  );
}
