import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

/**
 * Compact markdown for task notes. Loaded lazily (see tasks.tsx): the parser only
 * ships to the browser once a row is actually expanded.
 *
 * Everything is sized down to the dashboard's density: notes are working notes, so
 * headings act as quiet separators rather than page titles, and body text stays at
 * label size so a long file still reads inside a small scroll box.
 */
export default function MarkdownNotes({ children }: { children: string }) {
  return (
    <div className="space-y-2 text-xs leading-relaxed break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="text-sm font-semibold">{children}</h1>,
          h2: ({ children }) => (
            <h2 className="pt-1 text-xs font-semibold tracking-wide uppercase">{children}</h2>
          ),
          h3: ({ children }) => <h3 className="pt-0.5 text-xs font-medium">{children}</h3>,
          h4: ({ children }) => <h4 className="text-xs font-medium">{children}</h4>,
          p: ({ children }) => <p className="text-muted-foreground">{children}</p>,
          strong: ({ children }) => <strong className="font-medium text-foreground">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-sky-400 underline underline-offset-2"
            >
              {children}
            </a>
          ),
          ul: ({ children }) => (
            <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground marker:text-muted-foreground/60">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal space-y-0.5 pl-4 text-muted-foreground marker:text-muted-foreground/60">
              {children}
            </ol>
          ),
          li: ({ children }) => <li className="pl-0.5">{children}</li>,
          blockquote: ({ children }) => (
            // No italics: these notes quote whole state blocks, and a wall of italic text is
            // harder to read than the left rule alone.
            <blockquote className="space-y-2 border-l-2 border-border pl-2 text-muted-foreground">
              {children}
            </blockquote>
          ),
          hr: () => <hr className="border-border/60" />,
          code: ({ className, children }) => {
            // Fenced blocks arrive with a language class and are wrapped in <pre>; bare
            // inline code has neither, so it gets the chip treatment instead.
            const fenced = /language-/.test(className ?? "")
            return fenced ? (
              <code className="font-mono text-[11px] whitespace-pre-wrap">{children}</code>
            ) : (
              <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">{children}</code>
            )
          },
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-lg bg-muted/60 p-2 text-[11px] whitespace-pre-wrap">
              {children}
            </pre>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[11px]">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border border-border/60 px-1.5 py-1 text-left font-medium">{children}</th>
          ),
          td: ({ children }) => (
            <td className="border border-border/60 px-1.5 py-1 align-top text-muted-foreground">
              {children}
            </td>
          ),
          img: ({ src, alt }) => (
            <img src={typeof src === "string" ? src : undefined} alt={alt} className="max-w-full rounded" />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
