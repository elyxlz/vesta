import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useModals } from "@/providers/ModalsProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function DeleteCard() {
  const { name, isBusy } = useSelectedAgent();
  const { setDeleteDialogOpen } = useModals();

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="group-data-[size=sm]/card:text-base">
          <Trash2 className="size-4 text-destructive" />
          delete agent
        </CardTitle>
        <CardDescription className="group-data-[size=sm]/card:text-sm">
          permanently remove {name} and all its data. this cannot be undone.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex justify-end">
        <Button
          variant="destructive"
          disabled={isBusy}
          onClick={() => setDeleteDialogOpen(true)}
        >
          delete {name}
        </Button>
      </CardContent>
    </Card>
  );
}
