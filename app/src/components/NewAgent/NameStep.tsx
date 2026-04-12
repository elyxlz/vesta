import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { normalizeName } from "./types";

interface NameStepProps {
  name: string;
  onNameChange: (name: string) => void;
  onSubmit: () => void;
  onRestore: () => void;
  onCancel?: () => void;
  error: string;
  errorDetails: string;
}

export function NameStep({
  name,
  onNameChange,
  onSubmit,
  onRestore,
  onCancel,
  error,
  errorDetails,
}: NameStepProps) {
  const [showDetails, setShowDetails] = useState(false);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSubmit();
    if (e.key === "Escape" && onCancel) onCancel();
  };

  return (
    <div className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4">
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
            onChange={(e) => onNameChange(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
            className="text-center text-sm"
          />
        </Field>
      </FieldGroup>

      <Button
        onClick={onSubmit}
        disabled={!normalizeName(name)}
        className="w-full"
      >
        create
      </Button>

      <Button
        variant="link"
        onClick={onRestore}
        className="h-auto px-0 py-0 text-xs font-normal text-muted-foreground hover:bg-transparent hover:text-foreground"
      >
        restore from backup
      </Button>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>
            <p>{error}</p>
            {errorDetails && (
              <Collapsible open={showDetails} onOpenChange={setShowDetails}>
                <CollapsibleTrigger asChild>
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto px-0 text-destructive/70"
                  >
                    {showDetails ? "hide details" : "show details"}
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <p className="text-xs text-muted-foreground break-all">
                    {errorDetails}
                  </p>
                </CollapsibleContent>
              </Collapsible>
            )}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
