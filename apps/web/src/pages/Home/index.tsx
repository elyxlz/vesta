import { Home as HomeContent } from "@/components/Home";
import { UpdateProgressScreen } from "@/components/UpdateProgressScreen";
import { useGateway } from "@/providers/GatewayProvider";

export function Home() {
  const { gatewayOperation, updatedTo } = useGateway();
  if (gatewayOperation !== null || updatedTo !== null) {
    return <UpdateProgressScreen />;
  }
  return <HomeContent />;
}
