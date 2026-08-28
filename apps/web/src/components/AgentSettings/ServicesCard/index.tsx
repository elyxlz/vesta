import { Card, CardContent } from "@/components/ui/card";
import { MenuSection } from "@/components/ui/menu-section";
import { AgentServicesList } from "@/components/AgentServices";

export function ServicesCard() {
  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="services">
          <AgentServicesList />
        </MenuSection>
      </CardContent>
    </Card>
  );
}
