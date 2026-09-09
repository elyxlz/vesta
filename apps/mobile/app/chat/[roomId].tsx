import { useLocalSearchParams } from "expo-router";
import Stack from "expo-router/stack";
import ChatPage from "@/agent/ChatPage";
import { useChat } from "@/chat/chat-context";
import { RoomProvider } from "@/room/RoomProvider";

// A conversation that is not an agent's own: one stack screen titled by the room, holding the
// same chat surface the agent page shows.
function RoomScreenContent() {
  const { label } = useChat();
  return (
    <>
      <Stack.Screen options={{ title: label, headerTitleAlign: "center" }} />
      <ChatPage />
    </>
  );
}

export default function RoomScreen() {
  const parameters = useLocalSearchParams<{ roomId?: string }>();
  const roomId = typeof parameters.roomId === "string" ? parameters.roomId : "";
  return (
    <RoomProvider roomId={roomId}>
      <RoomScreenContent />
    </RoomProvider>
  );
}
