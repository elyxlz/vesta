import { Stack } from "expo-router";
import { AgentProvider } from "@/agent/AgentProvider";
import NotificationsPage from "@/agent/NotificationsPage";

function NotificationsContent() {
  return (
    <>
      <Stack.Screen options={{ title: "Notifications" }} />
      <NotificationsPage />
    </>
  );
}

export default function NotificationsScreen() {
  return (
    <AgentProvider>
      <NotificationsContent />
    </AgentProvider>
  );
}
