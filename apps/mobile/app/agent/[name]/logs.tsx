import { SheetTitle } from "@/components/sheet-title";
import LogsPage from "@/agent/LogsPage";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";

function LogsContent() {
  return (
    <>
      <SheetTitle>Logs</SheetTitle>
      <NativeSheetCloseButton accessibilityLabel="Close logs" />
      <SheetChrome title="Logs" closeLabel="Close logs" />
      <LogsPage presentation="standalone" />
    </>
  );
}

export default function LogsScreen() {
  return <LogsContent />;
}
