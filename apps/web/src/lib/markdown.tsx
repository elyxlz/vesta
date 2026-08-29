import ReactMarkdown from "react-markdown";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
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
            className="underline underline-offset-2 break-all"
          />
        ),
        code: ({ node: _n, className, children, ...props }) => {
          const isBlock = (className ?? "").includes("language-");
          return isBlock ? (
            <code
              {...props}
              className="block whitespace-pre overflow-x-auto rounded bg-black/20 px-2 py-1 my-1 text-[12px] font-mono"
            >
              {children}
            </code>
          ) : (
            <code
              {...props}
              className="rounded bg-black/15 px-1 py-0.5 text-[12px] font-mono"
            >
              {children}
            </code>
          );
        },
        pre: ({ children }) => <>{children}</>,
        ul: (p) => <ul {...p} className="list-disc pl-5 my-1" />,
        ol: (p) => <ol {...p} className="list-decimal pl-5 my-1" />,
        li: (p) => <li {...p} className="my-0.5" />,
        p: (p) => <p {...p} className="my-1 first:mt-0 last:mb-0" />,
        h1: (p) => <h1 {...p} className="text-base font-semibold my-1" />,
        h2: (p) => <h2 {...p} className="text-sm font-semibold my-1" />,
        h3: (p) => <h3 {...p} className="text-sm font-semibold my-1" />,
        blockquote: (p) => (
          <blockquote {...p} className="border-l-2 pl-2 opacity-80 my-1" />
        ),
        hr: () => <hr className="my-2 border-current opacity-20" />,
        table: (p) => (
          <div className="overflow-x-auto my-1">
            <table {...p} className="border-collapse text-[12px]" />
          </div>
        ),
        th: (p) => (
          <th {...p} className="border border-current/20 px-2 py-1 text-left" />
        ),
        td: (p) => <td {...p} className="border border-current/20 px-2 py-1" />,
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
