import { cn } from "@/lib/utils";

export function MenuSection({
  title,
  className,
  children,
}: {
  title: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <h3 className="text-xs font-medium text-muted-foreground px-1">{title}</h3>
      {children}
    </div>
  );
}
