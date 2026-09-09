import { SheetTitle } from "@/components/sheet-title";
import LogsPage from "@/agent/LogsPage";
import { NativeSheetCloseButton } from "@/components/native-sheet-close-button";
import { SheetChrome } from "@/components/sheet-chrome";

function LogsContent() {
  return (
    <>
      {process.env.EXPO_OS === "ios" ? (
        <>
          <SheetTitle>Logs</SheetTitle>
          <NativeSheetCloseButton accessibilityLabel="Close logs" />
        </>
      ) : null}
      <SheetChrome title="Logs" closeLabel="Close logs" />
      <LogsPage presentation="standalone" />
    </>
  );
}

export default function LogsScreen() {
  return <LogsContent />;
}
