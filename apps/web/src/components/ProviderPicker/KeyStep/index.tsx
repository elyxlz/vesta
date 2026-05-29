import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";

export function KeyStep({
  initialKey,
  initialZdr,
  onNext,
}: {
  initialKey: string;
  initialZdr: boolean;
  onNext: (key: string, zdr: boolean) => void;
}) {
  const [key, setKey] = useState(initialKey);
  const [zdr, setZdr] = useState(initialZdr);

  const canContinue = key.trim() !== "";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canContinue) return;
    onNext(key.trim(), zdr);
  };

  return (
    <form onSubmit={submit} className="flex w-full flex-col items-center gap-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">OpenRouter API key</h2>
        <FieldDescription>
          paste a key from openrouter.ai/keys. it stays on this machine.
        </FieldDescription>
      </div>

      <FieldGroup className="w-full gap-3">
        <Field>
          <FieldLabel htmlFor="or-key">API key</FieldLabel>
          <Input
            id="or-key"
            type="text"
            autoComplete="off"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            data-form-type="other"
            style={{ WebkitTextSecurity: "disc" } as React.CSSProperties}
            placeholder="sk-or-v1-..."
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoFocus
          />
        </Field>
        <div className="flex w-full items-center justify-between gap-3">
          <div className="flex flex-col">
            <span className="text-xs font-medium">zero data retention</span>
            <span className="text-[11px] text-muted-foreground">
              only route to providers that don't store data
            </span>
          </div>
          <Switch checked={zdr} onCheckedChange={setZdr} />
        </div>
      </FieldGroup>

      <Button type="submit" className="w-full" disabled={!canContinue}>
        next
      </Button>
    </form>
  );
}
