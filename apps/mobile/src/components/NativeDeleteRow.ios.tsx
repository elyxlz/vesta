import { StyleSheet, View } from "react-native";
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
} from "@expo/ui/swift-ui/modifiers";
import type { NativeDeleteRowProps } from "./NativeDeleteRow.types";

const rowModifiers = [
  frame({ height: 64 }),
  listRowBackground("#00000000"),
  listRowInsets({ top: 0, leading: 0, bottom: 0, trailing: 0 }),
  listRowSeparator("hidden"),
];

export function NativeDeleteRow({
  children,
  containerStyle,
  deleteAccessibilityLabel,
  disabled = false,
  onDelete,
}: NativeDeleteRowProps) {
  return (
    <Host colorScheme="light" ignoreSafeArea="all" style={styles.host}>
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
              role="destructive"
              onPress={onDelete}
              modifiers={[
                accessibilityLabel(deleteAccessibilityLabel),
                disabledModifier(disabled),
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
    height: 64,
    borderRadius: 18,
    overflow: "hidden",
  },
  content: { flex: 1 },
});
