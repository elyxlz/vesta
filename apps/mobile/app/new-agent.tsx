import { StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as WebBrowser from "expo-web-browser";
import { Screen } from "@/components/layout/Screen";
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
    <Screen scroll={false} contentStyle={styles.screen}>
      <View
        style={[styles.icon, { backgroundColor: colors.accentSoft }]}
      >
        <Ionicons name="desktop-outline" size={28} color={colors.accent} />
      </View>
      <View style={styles.copy}>
        <Text
          family="heading"
          style={[styles.title, { color: colors.text }]}
        >
          Coming soon
        </Text>
        <Text style={[styles.detail, { color: colors.secondaryText }]}>
          Agent creation is coming to mobile. For now, create new agents in
          Vesta Web. They’ll appear here automatically.
        </Text>
      </View>
      <Button
        pill
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
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    minHeight: 320,
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    paddingHorizontal: 28,
    paddingVertical: 36,
  },
  icon: {
    width: 58,
    height: 58,
    borderRadius: 29,
    alignItems: "center",
    justifyContent: "center",
  },
  copy: { alignItems: "center", gap: 8 },
  title: {
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "500",
    letterSpacing: -0.5,
    textAlign: "center",
  },
  detail: {
    maxWidth: 330,
    fontSize: 15,
    lineHeight: 22,
    textAlign: "center",
  },
});
