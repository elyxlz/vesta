import { useNavigate } from "react-router-dom";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { cn } from "@/lib/utils";
import { useGateway } from "@/providers/GatewayProvider";
import { glassPill } from "../../glass";
import { normalizeName } from "./normalize-name";

export function NameStep({
  value,
  onChange,
  onSubmit,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const navigate = useNavigate();
  const { agents } = useGateway();
  const trimmed = value.trim();
  const normalized = normalizeName(value);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSubmit();
    if (e.key === "Escape" && agents.length > 0) void navigate("/");
  };

  return (
    <div className="flex w-full flex-col items-center px-4">
      <FieldGroup className="gap-3">
        <Field>
          <FieldLabel htmlFor="agent-name" className="sr-only">
            Name
          </FieldLabel>
          <Input
            id="agent-name"
            placeholder="name your agent"
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
            }}
            onKeyDown={handleKeyDown}
            autoFocus
            className={cn("h-14 px-6 text-center", glassPill)}
          />
          {normalized !== trimmed && (
            <FieldDescription className="text-center">
              {normalized
                ? `will be called "${normalized}"`
                : "needs at least one letter or number"}
            </FieldDescription>
          )}
        </Field>
      </FieldGroup>
    </div>
  );
}
