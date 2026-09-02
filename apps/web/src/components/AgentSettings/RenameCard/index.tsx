import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { Input } from "@/components/ui/input";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { errorMessage } from "@/lib/utils";
import { renameAgent } from "@vesta/core";
import { httpClient } from "@/api/client";

export function RenameCard() {
  const { name, isBusy } = useSelectedAgent();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = value.trim();
  const invalid =
    trimmed.length === 0 ||
    trimmed === name ||
    (trimmed !== "vesta" && trimmed.includes("vesta"));

  const submit = async () => {
    if (invalid || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const finalName = await renameAgent(httpClient, name, trimmed);
      setOpen(false);
      await navigate(`/agent/${encodeURIComponent(finalName)}/settings`);
    } catch (e: unknown) {
      setError(errorMessage(e, "failed to rename"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <Pencil className="size-4" />
          rename agent
        </CardTitle>
        <CardDescription>
          give {name} a new name. they restart to take it, and their memory and
          backups carry over.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-end">
        <Button
          variant="outline"
          disabled={isBusy}
          onClick={() => {
            setValue(name);
            setError(null);
            setOpen(true);
          }}
        >
          rename {name}
        </Button>
      </CardContent>

      <Dialog drawerOnMobile open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md" showCloseButton>
          <DialogHeader>
            <DialogTitle>rename {name}</DialogTitle>
            <DialogDescription>
              spaces become hyphens and the name is lowercased. {name} restarts
              to take the new name.
            </DialogDescription>
          </DialogHeader>
          <Input
            autoFocus
            value={value}
            disabled={submitting}
            aria-invalid={value.trim().length > 0 && invalid}
            placeholder="new name"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
          />
          {error && <p className="text-xs text-destructive">{error}</p>}
          <DialogFooter showCloseButton>
            <Button
              disabled={invalid || submitting}
              onClick={() => void submit()}
            >
              {submitting ? "renaming..." : "rename"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
