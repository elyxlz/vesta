import type { ReactNode } from "react";
import { FieldDescription } from "@/components/ui/field";
import { cn } from "@/lib/utils";

export function StepHeading({
  title,
  description,
  className,
}: {
  title: string;
  description?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex w-full flex-col items-center gap-1 text-center",
        className,
      )}
    >
      <h2 className="font-heading text-lg font-medium tracking-tight">
        {title}
      </h2>
      {description && (
        <FieldDescription className="text-center text-[13px]">
          {description}
        </FieldDescription>
      )}
    </div>
  );
}
