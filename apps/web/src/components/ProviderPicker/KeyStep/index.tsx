import { useState, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { openrouterProvider } from "@/api";
import { errorMessage } from "@/lib/utils";
import { ProviderStep } from "../ProviderStep";

export function KeyStep({
  initialKey,
  onNext,
  logo,
  onCancel,
}: {
  initialKey: string;
  onNext: (key: string) => void;
  logo?: ReactNode;
  onCancel?: () => void;
}) {
  const [key, setKey] = useState(initialKey);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canContinue = key.trim() !== "" && !validating;

  const submit = async () => {
    if (!canContinue) return;
    setValidating(true);
    setError(null);
    try {
      await openrouterProvider.validateKey(key.trim());
      onNext(key.trim());
    } catch (e: unknown) {
      setError(errorMessage(e, "key validation failed"));
    } finally {
      setValidating(false);
    }
  };

  return (
    <ProviderStep
      logo={logo}
      title="OpenRouter API key"
      subtitle="paste a key from openrouter.ai/keys. it stays on this machine."
      submitLabel={validating ? "checking key..." : "next"}
      submitDisabled={!canContinue}
      onSubmit={() => {
        void submit();
      }}
      onCancel={onCancel}
      error={error}
    >
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
        className="w-full text-center"
      />
    </ProviderStep>
  );
}
