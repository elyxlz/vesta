import Stack from "expo-router/stack";
import LogsPage from "@/agent/LogsPage";

function LogsContent() {
  return (
    <>
      <Stack.Title>Logs</Stack.Title>
      <LogsPage presentation="standalone" />
    </>
  );
}

export default function LogsScreen() {
  return <LogsContent />;
}
