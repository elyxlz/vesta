import { StyleSheet, useWindowDimensions, View } from "react-native";
import {
  Button,
  Host,
  Image,
  List,
  RNHostView,
  SwipeActions,
} from "@expo/ui/swift-ui";
import {
  accessibilityLabel,
  disabled as disabledModifier,
  frame,
  listRowBackground,
  listRowInsets,
  listRowSeparator,
  listStyle,
  scrollContentBackground,
  scrollDisabled,
  tint,
} from "@expo/ui/swift-ui/modifiers";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";
import type { NativeDeleteRowProps } from "./NativeDeleteRow.types";

export function NativeDeleteRow({
  children,
  containerStyle,
  deleteAccessibilityLabel,
  dangerColor,
  disabled = false,
  onDelete,
}: NativeDeleteRowProps) {
  const { fontScale } = useWindowDimensions();
  const { dark } = usePreferences();
  const rowHeight = Math.max(64, Math.ceil(40 * fontScale + 24));
  const rowModifiers = [
    frame({ height: rowHeight }),
    listRowBackground("#00000000"),
    listRowInsets({ top: 0, leading: 0, bottom: 0, trailing: 0 }),
    listRowSeparator("hidden"),
  ];

  return (
    <Host
      colorScheme={dark ? "dark" : "light"}
      ignoreSafeArea="all"
      style={[styles.host, { height: rowHeight }]}
    >
      <List
        modifiers={[
          listStyle("plain"),
          scrollContentBackground("hidden"),
          scrollDisabled(),
        ]}
      >
        <SwipeActions modifiers={rowModifiers}>
          <RNHostView>
            <View style={[styles.content, containerStyle]}>{children}</View>
          </RNHostView>
          <SwipeActions.Actions edge="trailing" allowsFullSwipe={false}>
            <Button
              onPress={onDelete}
              modifiers={[
                accessibilityLabel(deleteAccessibilityLabel),
                disabledModifier(disabled),
                tint(dangerColor),
              ]}
            >
              <Image systemName="trash" />
            </Button>
          </SwipeActions.Actions>
        </SwipeActions>
      </List>
    </Host>
  );
}

const styles = StyleSheet.create({
  host: {
    alignSelf: "stretch",
    borderRadius: radii.card,
    borderCurve: "continuous",
    overflow: "hidden",
  },
  content: { flex: 1 },
});
