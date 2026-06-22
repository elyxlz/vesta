import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { openrouterProvider } from "@/api";
import { cn } from "@/lib/utils";

export function KeyStep({
  initialKey,
  onNext,
  hasBack,
}: {
  initialKey: string;
  onNext: (key: string) => void;
  hasBack?: boolean;
}) {
  const [key, setKey] = useState(initialKey);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canContinue = key.trim() !== "" && !validating;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canContinue) return;
    setValidating(true);
    setError(null);
    try {
      await openrouterProvider.validateKey(key.trim());
      onNext(key.trim());
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "key validation failed");
    } finally {
      setValidating(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex w-full flex-col items-start gap-4">
      <div className="flex flex-col items-start gap-1 text-left">
        <h2 className={cn("text-base font-semibold", hasBack && "pl-7")}>
          OpenRouter API key
        </h2>
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
            onChange={(e) => {
              setKey(e.target.value);
              if (error) setError(null);
            }}
            autoFocus
          />
          {error && <p className="text-[11px] text-destructive">{error}</p>}
        </Field>
      </FieldGroup>

      <Button type="submit" className="w-full" disabled={!canContinue}>
        {validating ? "checking key..." : "next"}
      </Button>
    </form>
  );
}
