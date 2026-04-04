import { useAuth } from "@/providers/AuthProvider";

export function Footer() {
  const { version } = useAuth();

  return (
    <div className="flex items-center justify-center h-11 shrink-0 select-none bg-background">
      {version ? (
        <span className="text-xs text-muted-foreground pointer-events-none">
          v{version}
        </span>
      ) : null}
    </div>
  );
}
