import { Component, type ErrorInfo, type ReactNode, useState } from "react";
import { useRouteError, isRouteErrorResponse } from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import {
  RotateCcw,
  ChevronDown,
  Home,
  AlertTriangle,
  Copy,
  Check,
} from "lucide-react";
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";
import { Button } from "@/components/ui/button";

interface ErrorBoundaryState {
  error: Error | null;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  override render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <ErrorFallback
            error={this.state.error}
            onReset={() => this.setState({ error: null })}
          />
        )
      );
    }

    return this.props.children;
  }
}

export function RouteErrorBoundary() {
  const error = useRouteError();

  if (isRouteErrorResponse(error)) {
    return (
      <ErrorFallback
        error={
          new Error(
            `${String(error.status)}: ${error.statusText || "page not found"}`,
          )
        }
        title={error.status === 404 ? "page not found" : "something went wrong"}
        description={
          error.status === 404
            ? "The page you're looking for doesn't exist or has been moved."
            : "An unexpected error occurred while loading this page."
        }
      />
    );
  }

  const resolvedError =
    error instanceof Error
      ? error
      : new Error(typeof error === "string" ? error : "Unknown error");

  return <ErrorFallback error={resolvedError} />;
}

interface ErrorFallbackProps {
  error: Error;
  title?: string;
  description?: string;
  onReset?: () => void;
}

function ErrorFallback({
  error,
  title = "something went wrong",
  description = "this shouldn't have happened. try again, or head back home.",
  onReset,
}: ErrorFallbackProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleRetry = () => {
    if (onReset) {
      onReset();
    } else {
      window.location.reload();
    }
  };

  const handleGoHome = () => {
    window.location.href = import.meta.env.BASE_URL;
  };

  const handleCopy = () => {
    const text = [error.message, error.stack].filter(Boolean).join("\n\n");
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        /* clipboard unavailable; leave the copied state untouched */
      });
  };

  return (
    <Empty className="h-full">
      <EmptyHeader>
        <EmptyMedia
          variant="icon"
          className="size-16 rounded-2xl bg-destructive/10 text-destructive"
        >
          <AlertTriangle className="size-8" strokeWidth={1.5} />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <div className="flex items-center gap-2">
          <Button onClick={handleRetry}>
            <RotateCcw data-icon="inline-start" />
            try again
          </Button>
          <Button variant="outline" onClick={handleGoHome}>
            <Home data-icon="inline-start" />
            go home
          </Button>
        </div>

        <div className="w-full">
          <button
            onClick={() => setDetailsOpen((prev) => !prev)}
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            <motion.div
              animate={{ rotate: detailsOpen ? 180 : 0 }}
              transition={{ duration: 0.2 }}
            >
              <ChevronDown className="size-3.5" />
            </motion.div>
            error details
          </button>

          <AnimatePresence>
            {detailsOpen && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <div className="relative mt-3 rounded-lg border border-border bg-muted/50 p-4 text-left">
                  <button
                    onClick={handleCopy}
                    className="absolute top-2 right-2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {copied ? (
                      <Check className="size-3.5" />
                    ) : (
                      <Copy className="size-3.5" />
                    )}
                  </button>
                  <p className="pr-8 font-mono text-xs leading-relaxed text-foreground">
                    {error.message}
                  </p>
                  {error.stack && (
                    <pre className="mt-2 max-h-40 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                      {error.stack
                        .split("\n")
                        .slice(1)
                        .map((line) => line.trim())
                        .join("\n")}
                    </pre>
                  )}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </EmptyContent>
    </Empty>
  );
}
