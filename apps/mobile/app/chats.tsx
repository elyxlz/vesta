import { StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import Stack from "expo-router/stack";
import { AgentsRow } from "@/chats/agents-row";
import { ChatsList } from "@/chats/chats-list";
import { HeaderButton } from "@/components/header-button";
import { Screen } from "@/components/layout/Screen";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

// The inbox: every agent's orb over every conversation, with the way to start a group in the
// header so a long list never scrolls it away.
export default function ChatsScreen() {
  const router = useRouter();
  const { colors } = usePreferences();
  const openNewRoom = () => router.push("/new-room");

  return (
    <Screen contentStyle={styles.screen}>
      <Stack.Screen
        options={{
          headerRight: IS_IOS
            ? undefined
            : () => (
                <HeaderButton
                  accessibilityLabel="New group"
                  icon="add"
                  iconSize={22}
                  onPress={openNewRoom}
                />
              ),
        }}
      />
      {IS_IOS ? (
        <Stack.Toolbar placement="right">
          <Stack.Toolbar.Button
            accessibilityLabel="New group"
            icon="plus"
            tintColor={colors.text}
            onPress={openNewRoom}
          />
        </Stack.Toolbar>
      ) : null}
      <AgentsRow />
      <ChatsList />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 16, gap: 8 },
});
