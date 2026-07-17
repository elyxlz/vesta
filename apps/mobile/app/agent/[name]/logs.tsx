import Stack from "expo-router/stack";
import LogsPage from "@/agent/LogsPage";

function LogsContent() {
  return (
    <>
      <Stack.Title>Logs</Stack.Title>
      <LogsPage />
    </>
  );
}

export default function LogsScreen() {
  return <LogsContent />;
}
