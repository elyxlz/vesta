import { LayoutDashboard } from "lucide-react";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyMedia,
} from "@/components/ui/empty";
import { widgets } from "./widgets";

export default function App() {
  if (widgets.length === 0) {
    return (
      <Empty className="flex-1 border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LayoutDashboard />
          </EmptyMedia>
          <EmptyTitle>your dashboard</EmptyTitle>
          <EmptyDescription>
            ask your agent to add some widgets
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 auto-rows-min">
      {widgets.map((w) => (
        <div
          key={w.id}
          className="bg-card border border-border rounded-lg shadow-sm overflow-hidden"
          style={{
            gridColumn: `span ${w.width ?? 1}`,
            gridRow: `span ${w.height ?? 1}`,
          }}
        >
          <w.component />
        </div>
      ))}
    </div>
  );
}
