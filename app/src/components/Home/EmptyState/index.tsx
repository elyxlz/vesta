import { EmptyDescription, EmptyHeader, EmptyTitle } from "@/components/ui/empty";

export function EmptyState() {
  return (
    <div className="flex h-full w-full items-center justify-center">
      <EmptyHeader>
        <EmptyTitle>no agents found</EmptyTitle>
        <EmptyDescription>create an agent to get started</EmptyDescription>
      </EmptyHeader>
    </div>
  );
}
