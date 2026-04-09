import {
  Component,
  type ErrorInfo,
  type ReactNode,
  useCallback,
  useState,
} from "react";
import {
  useRouteError,
  isRouteErrorResponse,
  useNavigate,
} from "react-router-dom";
import { motion, AnimatePresence } from "motion/react";
import {
  RotateCcw,
  ChevronDown,
  Home,
  AlertTriangle,
  Copy,
  Check,
} from "lucide-react";

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
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
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
          new Error(`${error.status} — ${error.statusText || "Page not found"}`)
        }
        title={error.status === 404 ? "Page not found" : "Something went wrong"}
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
      : new Error(String(error ?? "Unknown error"));

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
  title = "Something went wrong",
  description = "An unexpected error occurred. You can try again or go back home.",
  onReset,
}: ErrorFallbackProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  let navigate: ReturnType<typeof useNavigate> | null = null;

  try {
    navigate = useNavigate();
  } catch {
    // Outside router context
  }

  const handleRetry = useCallback(() => {
    if (onReset) {
      onReset();
    } else {
      window.location.reload();
    }
  }, [onReset]);

  const handleGoHome = useCallback(() => {
    if (navigate) {
      navigate("/home");
    } else {
      window.location.href = "/home";
    }
  }, [navigate]);

  const handleCopy = useCallback(() => {
    const text = [error.message, error.stack].filter(Boolean).join("\n\n");
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [error]);

  return (
    <div className="flex h-full w-full items-center justify-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.4, ease: [0.25, 0.46, 0.45, 0.94] }}
        className="flex w-full max-w-md flex-col items-center gap-6 text-center"
      >
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          transition={{
            delay: 0.1,
            type: "spring",
            stiffness: 200,
            damping: 20,
          }}
          className="flex h-16 w-16 items-center justify-center rounded-2xl bg-destructive/10"
        >
          <AlertTriangle
            className="h-8 w-8 text-destructive"
            strokeWidth={1.5}
          />
        </motion.div>

        <div className="flex flex-col gap-2">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRetry}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground shadow-sm transition-all hover:opacity-90 active:scale-[0.97]"
          >
            <RotateCcw className="h-4 w-4" />
            Try again
          </button>
          <button
            onClick={handleGoHome}
            className="inline-flex items-center gap-2 rounded-lg border border-border px-4 py-2.5 text-sm font-medium text-foreground shadow-sm transition-all hover:bg-accent active:scale-[0.97]"
          >
            <Home className="h-4 w-4" />
            Go home
          </button>
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
              <ChevronDown className="h-3.5 w-3.5" />
            </motion.div>
            Error details
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
                    className="absolute right-2 top-2 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {copied ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <p className="pr-8 font-mono text-xs leading-relaxed text-foreground">
                    {error.message}
                  </p>
                  {error.stack && (
                    <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-muted-foreground">
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
      </motion.div>
    </div>
  );
}
