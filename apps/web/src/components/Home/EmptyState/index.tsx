import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";

export function EmptyState() {
  const navigate = useNavigate();

  return (
    <div className="flex h-full w-full items-center justify-center">
      <Empty className="border-none">
        <EmptyHeader>
          <EmptyTitle>no agents yet</EmptyTitle>
          <EmptyDescription>create an agent to get started</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            onClick={() => {
              void navigate("/new");
            }}
          >
            <Plus data-icon="inline-start" />
            new agent
          </Button>
        </EmptyContent>
      </Empty>
    </div>
  );
}
