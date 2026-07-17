import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { SymbolView } from "expo-symbols";

const IS_IOS = process.env.EXPO_OS === "ios";

export function GatewaySettingsButton({
  color,
  connectedColor,
  disconnectedColor,
  reachable,
  label,
  onPress,
}: {
  color: string;
  connectedColor: string;
  disconnectedColor: string;
  reachable: boolean;
  label: string;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}, gateway ${reachable ? "connected" : "disconnected"}`}
      hitSlop={10}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { opacity: pressed ? 0.72 : 1 },
      ]}
    >
      <View style={styles.content}>
        <View
          accessibilityElementsHidden
          style={[
            styles.statusDot,
            {
              backgroundColor: reachable
                ? connectedColor
                : disconnectedColor,
            },
          ]}
        />
        {IS_IOS ? (
          <SymbolView
            name="gearshape"
            size={22}
            tintColor={color}
            resizeMode="scaleAspectFit"
          />
        ) : (
          <Ionicons name="settings-outline" size={22} color={color} />
        )}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 42,
    height: 42,
    borderRadius: 21,
    alignItems: "center",
    justifyContent: "center",
  },
  content: {
    flexDirection: "row",
    alignItems: "center",
    gap: 7,
  },
  statusDot: {
    width: 5,
    height: 5,
    borderRadius: 2.5,
  },
});
