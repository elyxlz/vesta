import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { createRoom } from "@vesta/core";
import { Screen } from "@/components/layout/Screen";
import { useBottomInset } from "@/components/layout/use-bottom-inset";
import { SheetChrome } from "@/components/sheet-chrome";
import { Button } from "@/components/ui/Button";
import { Field, FormSection, SwitchRow } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { useToast } from "@/components/native-toast";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useRoster } from "@/session/RosterProvider";
import { useSession } from "@/session/SessionProvider";

// Opening a group: a name and the agents that answer in it. The node answers with the room, and
// the conversation opens once that room reaches the tree, so the screen it lands on already knows
// what it is looking at.
export default function NewRoomScreen() {
  const router = useRouter();
  const { api } = useSession();
  const { agents, rooms } = useRoster();
  const { colors } = usePreferences();
  const { showError } = useToast();
  const bottomPadding = useBottomInset(24);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [opening, setOpening] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const canCreate = name.trim().length > 0 && members.length > 0 && !creating;
  const navigated = useRef(false);

  // The room is on the tree the moment /sync catches up; only then does the room screen resolve
  // it, so the wait is what keeps a fresh group from bouncing straight back Home.
  useEffect(() => {
    if (opening === null || navigated.current) return;
    if (!rooms.some((room) => room.id === opening)) return;
    navigated.current = true;
    router.replace({ pathname: "/chat/[roomId]", params: { roomId: opening } });
  }, [opening, rooms, router]);

  const toggle = (agent: string) => {
    setMembers((current) =>
      current.includes(agent)
        ? current.filter((member) => member !== agent)
        : [...current, agent],
    );
  };

  const create = () => {
    setCreating(true);
    createRoom(api, name.trim(), members).then(
      (opened) => {
        setOpening(opened.room.id);
      },
      (error: unknown) => {
        setCreating(false);
        showError(error, "Could not open the group");
      },
    );
  };

  return (
    <>
      <SheetChrome title="New group" closeLabel="Close new group" grabber />
      <Screen contentStyle={[styles.screen, { paddingBottom: bottomPadding }]}>
        <View style={styles.intro}>
          <Text family="heading" style={[styles.title, { color: colors.text }]}>
            New group
          </Text>
          <Text style={[styles.detail, { color: colors.secondaryText }]}>
            A conversation every agent you pick reads and answers in.
          </Text>
        </View>
        <Field
          autoFocus
          label="Name"
          placeholder="Trip planning"
          value={name}
          onChangeText={setName}
        />
        <FormSection title="Agents">
          {agents.map((agent) => (
            <SwitchRow
              key={agent.name}
              label={agent.name}
              value={members.includes(agent.name)}
              onValueChange={() => {
                toggle(agent.name);
              }}
            />
          ))}
        </FormSection>
        <Button pill disabled={!canCreate} loading={creating} onPress={create}>
          Create
        </Button>
      </Screen>
    </>
  );
}

const styles = StyleSheet.create({
  screen: { gap: 20, paddingHorizontal: 20, paddingTop: 28 },
  intro: { gap: 8 },
  title: { fontSize: 26, lineHeight: 32, fontWeight: "500" },
  detail: { fontSize: 15, lineHeight: 21 },
});
