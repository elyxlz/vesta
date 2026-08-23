import { useState } from "react";
import { StyleSheet, View, type LayoutChangeEvent } from "react-native";
import type { ThemePreference } from "@/preferences/PreferencesProvider";
import { designTokens } from "@/theme/generated";

const PREVIEW_HEIGHT = 56;

type Scheme = "light" | "dark";

// A simplified chat frame in one scheme: background, a card, an agent bubble
// line, and the primary send pill.
function SchemeFrame({ scheme }: { scheme: Scheme }) {
  const palette = designTokens.colors[scheme];
  return (
    <View style={[styles.frame, { backgroundColor: palette.background }]}>
      <View style={[styles.card, { backgroundColor: palette.card }]}>
        <View
          style={[
            styles.line,
            { backgroundColor: palette["muted-foreground"] },
          ]}
        />
        <View
          style={[
            styles.line,
            styles.shortLine,
            { backgroundColor: palette["muted-foreground"] },
          ]}
        />
      </View>
      <View style={[styles.pill, { backgroundColor: palette.primary }]} />
    </View>
  );
}

// The system tile shows light above and dark below a diagonal from the
// bottom-left to the top-right corner. A wedge rotated about the tile's
// center clips the dark frame, which is counter-rotated so it stays upright.
function SplitPreview() {
  const [width, setWidth] = useState(0);
  const angle = Math.atan2(PREVIEW_HEIGHT, width);
  const wedgeSize = 2 * Math.hypot(width, PREVIEW_HEIGHT);
  const onLayout = (event: LayoutChangeEvent) => {
    setWidth(event.nativeEvent.layout.width);
  };
  return (
    <View style={styles.split} onLayout={onLayout}>
      <SchemeFrame scheme="light" />
      {width > 0 ? (
        <View
          style={[
            styles.wedge,
            {
              left: width / 2 - wedgeSize / 2,
              top: PREVIEW_HEIGHT / 2,
              width: wedgeSize,
              height: wedgeSize,
              transform: [{ rotate: `${-angle}rad` }],
            },
          ]}
        >
          <View
            style={{
              position: "absolute",
              left: wedgeSize / 2 - width / 2,
              top: -PREVIEW_HEIGHT / 2,
              width,
              height: PREVIEW_HEIGHT,
              transform: [{ rotate: `${angle}rad` }],
            }}
          >
            <SchemeFrame scheme="dark" />
          </View>
        </View>
      ) : null}
    </View>
  );
}

export function AppearancePreview({ theme }: { theme: ThemePreference }) {
  if (theme === "system") return <SplitPreview />;
  return (
    <View style={styles.split}>
      <SchemeFrame scheme={theme} />
    </View>
  );
}

const styles = StyleSheet.create({
  split: {
    flexDirection: "row",
    alignSelf: "stretch",
    height: PREVIEW_HEIGHT,
    borderRadius: 8,
    borderCurve: "continuous",
    overflow: "hidden",
  },
  wedge: {
    position: "absolute",
    overflow: "hidden",
    transformOrigin: "top center",
  },
  frame: {
    flex: 1,
    padding: 8,
    justifyContent: "space-between",
  },
  card: {
    alignSelf: "flex-start",
    width: "56%",
    padding: 4,
    gap: 3,
    borderRadius: 4,
  },
  line: { height: 2, borderRadius: 1, opacity: 0.55 },
  shortLine: { width: "60%" },
  pill: { alignSelf: "flex-end", width: "40%", height: 6, borderRadius: 3 },
});
