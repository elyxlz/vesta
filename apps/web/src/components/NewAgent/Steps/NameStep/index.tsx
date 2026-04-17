import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import {
  createAgent,
  authenticate,
  type AuthStartResult,
} from "@/api";
import { useGateway } from "@/providers/GatewayProvider";
import { useOnboarding } from "@/stores/use-onboarding";

function normalizeName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function NameStep({
  onCreated,
}: {
  onCreated: (name: string, auth: AuthStartResult) => void;
}) {
  const navigate = useNavigate();
  const { agents } = useGateway();
  const setStep = useOnboarding((s) => s.setStep);
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  const handleCreate = async () => {
    const normalized = normalizeName(name);
    if (!normalized) return;

    setError("");
    setStep("creating");

    try {
      await createAgent(normalized);
      const auth = await authenticate(normalized);
      onCreated(normalized, auth);
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "creation failed");
      setStep("name");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape" && agents.length > 0) navigate("/");
  };

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">new agent</h2>
        <FieldDescription>give it a name to get started.</FieldDescription>
      </div>

      <FieldGroup className="gap-3">
        <Field>
          <FieldLabel htmlFor="agent-name" className="sr-only">
            Name
          </FieldLabel>
          <Input
            id="agent-name"
            placeholder="name your agent"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
            className="text-center text-sm"
          />
        </Field>
      </FieldGroup>

      <Button
        onClick={handleCreate}
        disabled={!normalizeName(name)}
        className="w-full"
      >
        create
      </Button>

      {error && (
        <p className="text-xs text-destructive text-center">{error}</p>
      )}
    </div>
  );
}
