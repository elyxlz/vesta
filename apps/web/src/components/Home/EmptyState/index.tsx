import { useNavigate } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty";

export function EmptyState() {
  const navigate = useNavigate();

  return (
    <div className="flex h-full w-full items-center justify-center">
      <EmptyHeader>
        <EmptyTitle>no agents found</EmptyTitle>
        <EmptyDescription>create an agent to get started</EmptyDescription>
        <EmptyContent>
          <Button onClick={() => navigate("/new")}>
            <Plus data-icon="inline-start" />
            new agent
          </Button>
        </EmptyContent>
      </EmptyHeader>
    </div>
  );
}
