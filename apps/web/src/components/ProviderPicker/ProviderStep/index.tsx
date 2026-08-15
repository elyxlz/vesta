import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { StepHeading } from "@/components/StepHeading";
import { cn } from "@/lib/utils";

// Shared layout for every provider step (Claude auth + each OpenRouter step).
// Standardizes the chrome — logo, title, subtitle, optional oauth link, a
// content slot, submit, optional back link — so a new provider's step is built
// by filling slots, not re-implementing the layout. Optional slots (logo,
// oauthLink, onBack, error) render only when provided, which lets the same
// step reused outside the picker (e.g. AgentSettings) drop them cleanly.
export function ProviderStep({
  logo,
  title,
  subtitle,
  oauthLink,
  children,
  submitLabel,
  submitDisabled = false,
  onSubmit,
  onBack,
  error,
  className,
}: {
  logo?: ReactNode;
  title: string;
  subtitle: ReactNode;
  oauthLink?: ReactNode;
  children?: ReactNode;
  submitLabel: ReactNode;
  submitDisabled?: boolean;
  onSubmit: () => void;
  onBack?: () => void;
  error?: string | null;
  className?: string;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className={cn("flex w-full flex-col items-center gap-5", className)}
    >
      {logo}
      <StepHeading title={title} description={subtitle} />
      {oauthLink}
      {children}
      {/* Actions are one semantic group: a small gap between submit/error/back,
          while the form's gap-5 keeps a big gap between heading, content, actions. */}
      <div className="flex w-full flex-col items-center gap-2">
        <Button type="submit" className="h-12 w-full" disabled={submitDisabled}>
          {submitLabel}
        </Button>
        {error && (
          <p className="text-xs text-destructive text-center">{error}</p>
        )}
        {onBack && (
          <Button
            type="button"
            variant="link"
            onClick={onBack}
            className="h-auto self-center px-0 py-0 text-xs font-normal text-muted-foreground hover:bg-transparent hover:text-foreground"
          >
            back
          </Button>
        )}
      </div>
    </form>
  );
}
