import { FieldDescription } from "@/components/ui/field";

export function StepHeading({
  title,
  description,
}: {
  title: string;
  description: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-1 text-center">
      <h2 className="text-base font-semibold">{title}</h2>
      <FieldDescription>{description}</FieldDescription>
    </div>
  );
}
