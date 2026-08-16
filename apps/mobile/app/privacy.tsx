import { SheetGateScreen } from "@/components/sheet-gate-screen";
import { PrivacySheet } from "@/privacy/privacy-sheet";

export default function PrivacyScreen() {
  return (
    <SheetGateScreen>
      <PrivacySheet />
    </SheetGateScreen>
  );
}
