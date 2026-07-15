import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/lib/markdown";
import { readFile } from "@/api/files";
import { DREAMER_PREFIX, parseDreamFilename } from "./paths";

interface DreamsViewerProps {
  agent: string;
  dreamPaths: string[];
}

interface DreamMeta {
  path: string;
  fname: string;
  date: Date | null;
}

export function DreamsViewer({ agent, dreamPaths }: DreamsViewerProps) {
  const pathsKey = dreamPaths.join("|");
  const entries = useMemo<DreamMeta[]>(() => {
    const metas = dreamPaths.map((path) => {
      const fname = path.slice(DREAMER_PREFIX.length);
      return { path, fname, date: parseDreamFilename(fname) };
    });
    metas.sort((a, b) => {
      if (a.date && b.date) return b.date.getTime() - a.date.getTime();
      return b.fname.localeCompare(a.fname);
    });
    return metas;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathsKey]);

  const [page, setPage] = useState(0);
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPage(0);
  }, [pathsKey]);

  const current = entries[page];
  const currentPath = current?.path ?? null;

  useEffect(() => {
    if (!currentPath) return;
    let cancelled = false;
    setContent(null);
    setError(null);
    readFile(agent, currentPath)
      .then((r) => {
        if (cancelled) return;
        setContent(r.encoding === "utf-8" ? r.content : "");
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [agent, currentPath]);

  return (
    <div className="flex h-full flex-col bg-gradient-to-b from-card to-muted/20">
      <header className="flex shrink-0 items-center justify-center gap-2 py-6 text-muted-foreground">
        <Moon className="size-4" />
        <span className="font-serif text-sm italic tracking-wider uppercase">
          dream journal
        </span>
        <Moon className="size-4 -scale-x-100" />
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-2xl px-6 pb-8">
          {entries.length === 0 ? (
            <p className="text-center font-serif text-sm italic text-muted-foreground/70">
              no dreams yet — the agent journals nightly while you sleep
            </p>
          ) : error ? (
            <p className="text-center text-sm text-destructive">
              failed to load: {error}
            </p>
          ) : content === null || !current ? (
            <div className="flex flex-col gap-6">
              <Skeleton className="mx-auto h-6 w-48 rounded" />
              <Skeleton className="h-40 w-full rounded-lg" />
            </div>
          ) : (
            <DreamEntryView entry={current} content={content} />
          )}
        </div>
      </div>

      {entries.length > 1 && (
        <nav className="flex shrink-0 items-center justify-center gap-4 py-4">
          <Button
            variant="ghost"
            size="icon"
            aria-label="newer dream"
            disabled={page === 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="font-serif text-xs italic tabular-nums text-muted-foreground/70">
            {page + 1} / {entries.length}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="older dream"
            disabled={page === entries.length - 1}
            onClick={() => setPage((p) => Math.min(entries.length - 1, p + 1))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </nav>
      )}
    </div>
  );
}

function DreamEntryView({
  entry,
  content,
}: {
  entry: DreamMeta;
  content: string;
}) {
  const dateLabel = entry.date
    ? new Intl.DateTimeFormat(undefined, {
        weekday: "long",
        month: "long",
        day: "numeric",
        year: "numeric",
      }).format(entry.date)
    : entry.fname.replace(/\.md$/, "");
  const timeLabel = entry.date
    ? new Intl.DateTimeFormat(undefined, {
        hour: "numeric",
        minute: "2-digit",
      }).format(entry.date)
    : null;

  return (
    <>
      <div className="mb-3 text-center">
        <h2 className="font-serif text-xl italic text-foreground/90">
          {dateLabel}
        </h2>
        {timeLabel && (
          <p className="mt-0.5 font-serif text-xs italic text-muted-foreground/70">
            {timeLabel}
          </p>
        )}
      </div>
      <div className="font-serif text-[13px] leading-relaxed text-foreground/85 [&_p]:my-2 [&_h1]:font-serif [&_h2]:font-serif [&_h3]:font-serif [&_h1]:italic [&_h2]:italic [&_h3]:italic">
        <Markdown>{content}</Markdown>
      </div>
    </>
  );
}
