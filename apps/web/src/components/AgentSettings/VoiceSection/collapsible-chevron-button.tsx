// The trigger row of every collapsible in the voice settings.
import { ChevronDown } from "lucide-react";
import { CollapsibleTrigger } from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";

export function CollapsibleChevronButton({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <CollapsibleTrigger asChild>
      <Button
        variant="ghost"
        size="sm"
        className="w-full justify-start gap-2 px-0 text-base text-muted-foreground hover:text-foreground"
      >
        <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
        {children}
      </Button>
    </CollapsibleTrigger>
  );
}
