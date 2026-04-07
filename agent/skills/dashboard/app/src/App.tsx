import { widgets } from "./widgets";

export default function App() {
  if (widgets.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        No widgets yet. Ask your agent to create one.
      </div>
    );
  }

  return (
    <div className="p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 auto-rows-min">
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
