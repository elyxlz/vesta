import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { MenuSection } from "@/components/ui/menu-section";
import { Switch } from "@/components/ui/switch";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { usePreferences } from "@/stores/use-preferences";

export function ChatCard() {
  const { name } = useSelectedAgent();
  const natural = usePreferences((s) => s.naturalPacingByAgent[name] ?? true);
  const update = usePreferences((s) => s.update);
  const setNatural = (value: boolean) => {
    update({
      naturalPacingByAgent: {
        ...usePreferences.getState().naturalPacingByAgent,
        [name]: value,
      },
    });
  };

  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="chat">
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel className="text-base">natural pacing</FieldLabel>
              <FieldDescription>
                simulate typing delay before this agent's replies appear
              </FieldDescription>
            </FieldContent>
            <Switch checked={natural} onCheckedChange={setNatural} />
          </Field>
        </MenuSection>
      </CardContent>
    </Card>
  );
}
