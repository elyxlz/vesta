import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { CodeBlock } from "@/components/CodeBlock";
import { splitTextIntoLinks, type MdastNode } from "./bare-url";

function linkifyNode(node: MdastNode): void {
  const children = node.children;
  if (!children) return;
  const next: MdastNode[] = [];
  for (const child of children) {
    if (child.type === "text" && child.value) {
      next.push(...splitTextIntoLinks(child.value));
      continue;
    }
    // Don't descend into existing links or code; everything else can hold linkifiable text.
    if (
      child.type !== "link" &&
      child.type !== "inlineCode" &&
      child.type !== "code"
    ) {
      linkifyNode(child);
    }
    next.push(child);
  }
  node.children = next;
}

function remarkLinkifyBareUrls() {
  return (tree: MdastNode) => {
    linkifyNode(tree);
  };
}

export function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks, remarkLinkifyBareUrls]}
      components={{
        a: ({ node: _n, ...props }) => (
          <a
            {...props}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium text-interactive group-data-[variant=default]/bubble:text-current underline decoration-1 underline-offset-2 wrap-anywhere"
          />
        ),
        code: ({ node: _n, className: _c, ...props }) => (
          <code
            {...props}
            className="rounded-[5px] bg-current/10 px-1 py-px font-mono text-[0.9em]"
          />
        ),
        // A fence always parses to pre > code, with or without a language, so the
        // block decision reads the tree instead of the class name.
        pre: ({ node }) => {
          const codeNode = node?.children[0];
          if (codeNode?.type !== "element") return null;
          const classes = codeNode.properties.className;
          const language = Array.isArray(classes)
            ? classes
                .map(String)
                .find((name) => name.startsWith("language-"))
                ?.slice("language-".length)
            : undefined;
          const text = codeNode.children
            .map((child) => (child.type === "text" ? child.value : ""))
            .join("")
            .replace(/\n$/, "");
          return <CodeBlock code={text} info={language ?? null} />;
        },
        ul: (p) => (
          <ul
            {...p}
            className="my-1 list-disc pl-5 marker:text-muted-foreground"
          />
        ),
        ol: (p) => (
          <ol
            {...p}
            className="my-1 list-decimal pl-5 marker:text-muted-foreground"
          />
        ),
        li: (p) => <li {...p} className="my-1 pl-0.5" />,
        p: (p) => <p {...p} className="mb-2 last:mb-0" />,
        h1: (p) => (
          <h1
            {...p}
            className="mt-1 mb-1.5 text-[1.25em] leading-tight font-semibold"
          />
        ),
        h2: (p) => (
          <h2
            {...p}
            className="mt-1 mb-1 text-[1.125em] leading-tight font-semibold"
          />
        ),
        h3: (p) => <h3 {...p} className="mt-1 mb-1 font-semibold" />,
        h4: (p) => (
          <h4
            {...p}
            className="mt-1 mb-1 text-[0.9375em] font-semibold text-muted-foreground"
          />
        ),
        h5: (p) => (
          <h5
            {...p}
            className="mt-1 mb-1 text-[0.9375em] font-semibold text-muted-foreground"
          />
        ),
        h6: (p) => (
          <h6
            {...p}
            className="mt-1 mb-1 text-[0.9375em] font-semibold text-muted-foreground"
          />
        ),
        blockquote: (p) => (
          <blockquote
            {...p}
            className="relative my-1.5 rounded-2xl bg-current/10 py-1.5 pr-2.5 pl-5 before:absolute before:top-2 before:bottom-2 before:left-2.5 before:w-[3px] before:rounded-full before:bg-current before:opacity-60 before:content-['']"
          />
        ),
        hr: () => <hr className="my-3 border-border" />,
        table: (p) => (
          <div className="my-2 overflow-x-auto rounded-[9px] border border-border">
            <table {...p} className="w-full border-collapse text-[0.875em]" />
          </div>
        ),
        th: (p) => (
          <th
            {...p}
            className="border-b border-border bg-input px-2 py-1.5 text-left font-semibold"
          />
        ),
        td: (p) => <td {...p} className="border-t border-border px-2 py-1.5" />,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
