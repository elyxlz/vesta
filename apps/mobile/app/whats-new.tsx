import { Pressable, StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { filterReleaseNotes } from "@vesta/core";
import { Stack, useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { Screen } from "@/components/layout/Screen";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { releaseNotesQueryOptions } from "@/releases/release-notes-query";
import { useRoster } from "@/session/RosterProvider";
import { radii } from "@/theme/layout";

const IS_IOS = process.env.EXPO_OS === "ios";

function formatReleaseDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function WhatsNewScreen() {
  const router = useRouter();
  const roster = useRoster();
  const { colors } = usePreferences();
  const notes = useQuery({
    ...releaseNotesQueryOptions(roster.gatewayVersion),
    enabled: Boolean(roster.gatewayVersion && roster.gatewayChannel),
  });
  const visible =
    notes.data && roster.gatewayVersion && roster.gatewayChannel
      ? filterReleaseNotes(notes.data, {
          version: roster.gatewayVersion,
          channel: roster.gatewayChannel,
        })
      : [];

  return (
    <>
      <Screen contentStyle={styles.content}>
        {notes.isPending || !roster.gatewayVersion || !roster.gatewayChannel ? (
          <LoadingState label="Loading release notes…" />
        ) : notes.isError ? (
          <ErrorState
            message="Couldn’t load release notes."
            retry={() => void notes.refetch()}
          />
        ) : visible.length === 0 ? (
          <EmptyState
            title="Nothing new yet"
            detail="Check back after the next update."
          />
        ) : (
          <View style={styles.releaseList}>
            {visible.map((entry) => (
              <View
                key={entry.version}
                style={[
                  styles.releaseCard,
                  { backgroundColor: colors.card, borderColor: colors.border },
                ]}
              >
                <View style={styles.releaseHeader}>
                  <Text style={[styles.version, { color: colors.text }]}>
                    v{entry.version}
                  </Text>
                  <Text style={[styles.date, { color: colors.tertiaryText }]}>
                    {formatReleaseDate(entry.date)}
                  </Text>
                  <Pressable
                    accessibilityRole="link"
                    accessibilityLabel={`View release v${entry.version} on GitHub`}
                    hitSlop={13}
                    onPress={() => {
                      void WebBrowser.openBrowserAsync(entry.url, {
                        presentationStyle:
                          WebBrowser.WebBrowserPresentationStyle.PAGE_SHEET,
                      });
                    }}
                    style={styles.releaseLink}
                  >
                    {({ pressed }) => (
                      <Text
                        style={[
                          styles.releaseLinkText,
                          {
                            color: pressed
                              ? colors.interactive
                              : colors.tertiaryText,
                          },
                        ]}
                      >
                        View on GitHub
                      </Text>
                    )}
                  </Pressable>
                </View>
                <Text
                  selectable
                  style={[styles.message, { color: colors.secondaryText }]}
                >
                  {entry.message}
                </Text>
              </View>
            ))}
          </View>
        )}
      </Screen>
      <Stack.Toolbar placement="left">
        <Stack.Toolbar.Button
          accessibilityLabel="Close What’s New"
          icon={IS_IOS ? "xmark" : undefined}
          separateBackground
          tintColor={colors.text}
          onPress={() => router.back()}
        >
          {IS_IOS ? undefined : "Close"}
        </Stack.Toolbar.Button>
      </Stack.Toolbar>
    </>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24, paddingBottom: 80 },
  releaseList: { gap: 12 },
  releaseCard: {
    borderRadius: radii.card,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    gap: 8,
    padding: 16,
  },
  releaseHeader: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  version: { fontSize: 16, fontWeight: "600" },
  date: { fontSize: 13 },
  message: { fontSize: 15, lineHeight: 21 },
  releaseLink: { marginLeft: "auto" },
  releaseLinkText: { fontSize: 12, fontWeight: "500" },
});
