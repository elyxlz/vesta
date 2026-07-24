import { StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { filterReleaseNotes } from "@vesta/core";
import { Stack, useRouter } from "expo-router";
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
          <View
            style={[
              styles.releaseList,
              { backgroundColor: colors.card, borderColor: colors.border },
            ]}
          >
            {visible.map((entry, index) => (
              <View key={entry.version}>
                {index > 0 ? (
                  <View
                    style={[
                      styles.separator,
                      { backgroundColor: colors.border },
                    ]}
                  />
                ) : null}
                <View style={styles.release}>
                  <View style={styles.releaseHeader}>
                    <Text style={[styles.version, { color: colors.text }]}>
                      v{entry.version}
                    </Text>
                    <Text style={[styles.date, { color: colors.tertiaryText }]}>
                      {formatReleaseDate(entry.date)}
                    </Text>
                  </View>
                  <Text
                    selectable
                    style={[styles.message, { color: colors.secondaryText }]}
                  >
                    {entry.message}
                  </Text>
                </View>
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
  releaseList: {
    borderRadius: radii.card,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
  },
  release: { gap: 8, padding: 16 },
  releaseHeader: { flexDirection: "row", alignItems: "baseline", gap: 8 },
  version: { fontSize: 16, fontWeight: "600" },
  date: { fontSize: 13 },
  message: { fontSize: 15, lineHeight: 21 },
  separator: {
    height: StyleSheet.hairlineWidth,
    marginHorizontal: 16,
  },
});
