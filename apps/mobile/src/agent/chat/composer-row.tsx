import { useState, type ReactNode } from "react";
import { StyleSheet, Text, View, type LayoutChangeEvent } from "react-native";
import { composerExpandedNext } from "@vesta/core";
import { CHAT_COMPOSER_INPUT_HORIZONTAL_PADDING } from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

// One line while the text fits beside the buttons. Once it would wrap, the input keeps its line
// alone and the buttons move to a line below. The input never changes parent or index: a native
// reorder is a remove and re-insert, which drops the keyboard. The decision measures the text as
// a single line against the collapsed input width, so growth inside the expanded row can never
// flip it back and forth.
export function ComposerRow({
  value,
  attach,
  input,
  actions,
}: {
  value: string;
  attach: ReactNode;
  input: ReactNode;
  actions: ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const [collapsedWidth, setCollapsedWidth] = useState(0);
  const [mirrorWidth, setMirrorWidth] = useState(0);
  const next = composerExpandedNext(
    expanded,
    value,
    collapsedWidth,
    mirrorWidth,
  );
  if (next !== expanded) setExpanded(next);

  const onInputLayout = (event: LayoutChangeEvent) => {
    if (expanded) return;
    setCollapsedWidth(
      event.nativeEvent.layout.width -
        2 * CHAT_COMPOSER_INPUT_HORIZONTAL_PADDING,
    );
  };
  const onMirrorLayout = (event: LayoutChangeEvent) => {
    setMirrorWidth(event.nativeEvent.layout.width);
  };

  return (
    <View>
      <Text
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
        numberOfLines={1}
        onLayout={onMirrorLayout}
        pointerEvents="none"
        style={styles.mirror}
      >
        {value || " "}
      </Text>
      <View style={styles.line}>
        <View>{expanded ? null : attach}</View>
        <View onLayout={onInputLayout} style={styles.input}>
          {input}
        </View>
        <View>{expanded ? null : actions}</View>
      </View>
      {expanded ? (
        <View style={styles.buttons}>
          {attach}
          <View style={styles.spacer} />
          {actions}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  line: { flexDirection: "row", alignItems: "flex-end" },
  // A row, so the input's own `flex: 1` keeps meaning width and its height stays content-driven.
  input: { flex: 1, minWidth: 0, flexDirection: "row" },
  buttons: { flexDirection: "row", alignItems: "center", marginTop: 4 },
  spacer: { flex: 1 },
  mirror: {
    position: "absolute",
    top: 0,
    left: 0,
    opacity: 0,
    fontFamily: fontNames.sans.native["400"],
    fontSize: 17,
  },
});
