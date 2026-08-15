import { useNavigate } from "react-router-dom";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { cn } from "@/lib/utils";
import { useGateway } from "@/providers/GatewayProvider";
import { glassPill } from "../../glass";

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
            // One word only: whitespace is dropped as it is typed or pasted.
            onChange={(e) => {
              onChange(e.target.value.replace(/\s+/g, ""));
            }}
            onKeyDown={handleKeyDown}
            autoFocus
            className={cn("h-14 px-6 text-center", glassPill)}
          />
        </Field>
      </FieldGroup>
    </div>
  );
}
