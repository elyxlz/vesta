import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
} from "@/components/ui/empty";

export function Dashboard() {
  return (
    <Empty className="flex-1 border-0">
      <EmptyHeader>
        <EmptyTitle>your dashboard</EmptyTitle>
        <EmptyDescription>
          ask your agent to build this dashboard however you'd like
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}
