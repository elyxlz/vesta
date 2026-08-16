import { SheetGateScreen } from "@/components/sheet-gate-screen";
import { GatewayUpdateSheet } from "@/controller/gateway-update-sheet";

export default function GatewayUpdateScreen() {
  return (
    <SheetGateScreen>
      <GatewayUpdateSheet />
    </SheetGateScreen>
  );
}
