import { useEffect, useRef, useState } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

// The one OAuth-link treatment every provider auth step shares: the URL
// truncated to one line with a copy button beside it, so a long auth link
// never breaks the step layout. The link auto-opens in a new tab the moment
// the step renders, so the user lands on the provider's sign-in page at once.
export function OAuthLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const openedFor = useRef<string | null>(null);

  useEffect(() => {
    if (openedFor.current === url) return;
    openedFor.current = url;
    window.open(url, "_blank", "noopener");
  }, [url]);

  const copy = () => {
    void navigator.clipboard
      .writeText(url)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      })
      .catch(() => {
        /* clipboard unavailable; the link stays visible for a manual copy */
      });
  };

  return (
    <div className="flex w-full min-w-0 max-w-full items-center justify-center gap-1.5 overflow-hidden">
      <a
        href={url}
        target="_blank"
        rel="noopener"
        className="min-w-0 truncate text-xs text-muted-foreground hover:text-foreground"
      >
        {url}
      </a>
      <Button
        variant="ghost"
        size="icon-xs"
        className="shrink-0"
        type="button"
        aria-label={copied ? "copied" : "copy auth link"}
        onClick={copy}
      >
        {copied ? <Check /> : <Copy />}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {copied ? "copied" : ""}
      </span>
    </div>
  );
}
