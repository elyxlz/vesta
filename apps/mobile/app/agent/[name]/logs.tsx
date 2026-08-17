import Stack from "expo-router/stack";
import LogsPage from "@/agent/LogsPage";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";

function LogsContent() {
  return (
    <>
      <Stack.Title>Logs</Stack.Title>
      <NativeSheetCloseButton accessibilityLabel="Close logs" />
      <SheetChrome title="Logs" closeLabel="Close logs" />
      <LogsPage presentation="standalone" />
    </>
  );
}

export default function LogsScreen() {
  return <LogsContent />;
}
