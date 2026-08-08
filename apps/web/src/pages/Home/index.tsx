import { Home as HomeContent } from "@/components/Home";
import { UpdateProgressScreen } from "@/components/UpdateProgressScreen";
import { useGateway } from "@/providers/GatewayProvider";

export function Home() {
  const { updateOperation, updatedTo } = useGateway();
  if (updateOperation !== null || updatedTo !== null) {
    return <UpdateProgressScreen />;
  }
  return <HomeContent />;
}
