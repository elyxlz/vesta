import { StyleSheet, View } from "react-native";
import * as WebBrowser from "expo-web-browser";
import { Screen } from "@/components/layout/Screen";
import { useBottomInset } from "@/components/layout/use-bottom-inset";
import { SheetChrome } from "@/components/sheet-chrome";
import { Button } from "@/components/ui/Button";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

export default function NewAgentScreen() {
  const { connection } = useSession();
  const { colors } = usePreferences();
  const bottomPadding = useBottomInset(24);
  const webUrl = connection
    ? `${connection.url.replace(/\/+$/, "")}/app/new`
    : "https://vesta.run/app/new";

  return (
    <>
      <SheetChrome grabber />
      <Screen
        scroll={false}
        contentStyle={[styles.screen, { paddingBottom: bottomPadding }]}
      >
        <View style={styles.copy}>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            Only on web
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
    </>
  );
}

const styles = StyleSheet.create({
  screen: {
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    paddingHorizontal: 24,
    paddingTop: 36,
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
