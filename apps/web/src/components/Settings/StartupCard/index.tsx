import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { MenuSection } from "@/components/ui/menu-section";
import { Switch } from "@/components/ui/switch";
import { useLoginItem } from "./use-login-item";

// Desktop only: the OS launch-at-login toggle. Hidden in the browser, where native.loginItem is null.
export function StartupCard() {
  const { supported, enabled, setEnabled } = useLoginItem();
  if (!supported) return null;
  return (
    <Card size="sm">
      <CardContent>
        <MenuSection title="startup">
          <Field
            orientation="horizontal"
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel className="text-base">launch on startup</FieldLabel>
              <FieldDescription>
                open automatically when you sign in to this computer
              </FieldDescription>
            </FieldContent>
            <Switch
              checked={enabled}
              onCheckedChange={(value) => {
                void setEnabled(value);
              }}
            />
          </Field>
        </MenuSection>
      </CardContent>
    </Card>
  );
}
