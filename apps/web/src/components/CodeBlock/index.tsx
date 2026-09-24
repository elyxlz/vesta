import { useMemo, useState } from "react";
import { CODE_TOKEN_COLORS, highlightCode } from "@vesta/core";

const COPIED_MS = 1500;

export function CodeBlock({
  code,
  info,
}: {
  code: string;
  info: string | null;
}) {
  const highlighted = useMemo(() => highlightCode(code, info), [code, info]);
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard
      .writeText(code)
      .then(() => {
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, COPIED_MS);
      })
      .catch(() => undefined);
  };
  return (
    <div className="my-1.5 overflow-hidden rounded-[11px] border border-border bg-code text-foreground">
      <div className="flex items-center justify-between gap-3 px-2.5 pt-1.5 text-xs text-muted-foreground select-none">
        <span>{highlighted.language ?? "code"}</span>
        <button
          type="button"
          onClick={copy}
          className="rounded px-1 transition-colors hover:text-foreground"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-2.5 pt-1 pb-2 font-mono text-[0.8125em] leading-[1.46]">
        <code>
          {highlighted.lines.map((line, lineIndex) => (
            <span key={lineIndex} className="block min-h-[1lh]">
              {line.map((token, tokenIndex) => (
                <span
                  key={tokenIndex}
                  style={{ color: `var(--${CODE_TOKEN_COLORS[token.kind]})` }}
                >
                  {token.text}
                </span>
              ))}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
