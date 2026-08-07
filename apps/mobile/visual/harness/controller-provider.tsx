import type { ReactNode } from "react";
import * as Linking from "expo-linking";
import { GatewayUpdateGate } from "../../src/controller/gateway-update-gate";
import { ControllerContext } from "../../src/controller/context";

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const needsGatewayUpdate = query?.visualGatewayUpdate === "required";

export function ControllerProvider({ children }: { children: ReactNode }) {
  return (
    <ControllerContext.Provider value={null}>
      <GatewayUpdateGate blocked={needsGatewayUpdate}>
        {children}
      </GatewayUpdateGate>
    </ControllerContext.Provider>
  );
}
