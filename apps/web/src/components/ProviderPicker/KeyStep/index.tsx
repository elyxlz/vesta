import { useState, type ReactNode } from "react";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/utils";
import { ProviderStep } from "../ProviderStep";

export function KeyStep({
  initialKey,
  onNext,
  logo,
  onCancel,
  title,
  subtitle,
  placeholder,
  validateKey,
}: {
  initialKey: string;
  onNext: (key: string) => void;
  logo?: ReactNode;
  onCancel?: () => void;
  title: string;
  subtitle: string;
  placeholder?: string;
  validateKey?: (key: string) => Promise<void>;
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
      await validateKey?.(key.trim());
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
      title={title}
      subtitle={subtitle}
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
        placeholder={placeholder}
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
