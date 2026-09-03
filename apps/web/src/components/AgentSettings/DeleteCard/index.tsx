import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useDialogs } from "@/stores/use-dialogs";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";

export function DeleteCard() {
  const { name, isBusy } = useSelectedAgent();
  const openDialog = useDialogs((s) => s.setOpen);

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <Trash2 className="size-4 text-destructive" />
          delete agent
        </CardTitle>
        <CardDescription>
          permanently remove {name} and all its data. this cannot be undone.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-end">
        <Button
          variant="destructive"
          disabled={isBusy}
          onClick={() => openDialog("deleteAgent", true)}
        >
          delete {name}
        </Button>
      </CardContent>
    </Card>
  );
}
