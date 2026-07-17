import { Button } from "@/components/ui/button";
import { MenuSection } from "@/components/ui/menu-section";
import { buildActionSections, type AgentActionsInput } from "./action-sections";

export function AgentActions({
  wrapper: Wrapper = PassThrough,
  ...input
}: AgentActionsInput & {
  wrapper?: React.ComponentType<{ children: React.ReactNode }>;
}) {
  const sections = buildActionSections(input);

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <MenuSection key={section.key} title={section.title}>
          {section.items.map((item) => (
            <Wrapper key={item.key}>
              <Button
                variant={item.variant ?? "secondary"}
                className="w-full justify-start"
                disabled={item.disabled}
                onClick={item.onClick}
              >
                {item.icon}
                {item.label}
              </Button>
            </Wrapper>
          ))}
        </MenuSection>
      ))}
    </div>
  );
}

function PassThrough({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
