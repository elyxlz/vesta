import { Stack } from "expo-router";
import { AgentProvider } from "@/agent/AgentProvider";
import LogsPage from "@/agent/LogsPage";

function LogsContent() {
  return (
    <>
      <Stack.Screen options={{ title: "Logs" }} />
      <LogsPage />
    </>
  );
}

export default function LogsScreen() {
  return (
    <AgentProvider>
      <LogsContent />
    </AgentProvider>
  );
}
