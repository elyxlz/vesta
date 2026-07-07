import { cn } from "@/lib/utils";

export function MenuSection({
  title,
  trailing,
  className,
  children,
}: {
  title: string;
  trailing?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <div className="flex min-w-0 items-baseline gap-2">
        <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
        {trailing}
      </div>
      {children}
    </div>
  );
}
