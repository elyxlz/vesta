import { StyleSheet, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { AuthSheet } from "@/components/auth-sheet";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export default function NewAgentScreen() {
  const { connection } = useSession();
  const { colors } = usePreferences();
  const webUrl = connection
    ? `${connection.url.replace(/\/+$/, "")}/app/new`
    : "https://vesta.run/app/new";

  return (
    <AuthSheet title="Only on web" hasGrabber>
      <View style={styles.screen}>
        <View style={styles.copy}>
          <Text style={[styles.detail, { color: colors.secondaryText }]}>
            Agent creation is coming to mobile. For now, create new agents in
            Vesta Web. They’ll appear here automatically.
          </Text>
        </View>
        <Button
          icon="open-outline"
          onPress={() => {
            void WebBrowser.openBrowserAsync(webUrl, {
              presentationStyle:
                WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
            });
          }}
        >
          Open Vesta Web
        </Button>
      </View>
    </AuthSheet>
  );
}

const styles = StyleSheet.create({
  screen: {
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    paddingTop: 8,
  },
  copy: { alignItems: "center", gap: 8 },
  detail: {
    maxWidth: 330,
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
  },
});
