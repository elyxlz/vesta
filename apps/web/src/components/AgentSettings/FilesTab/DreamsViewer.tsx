import { useMemo, useState } from "react";
import { useResource } from "@vesta/core/react";
import { ChevronLeft, ChevronRight, Moon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/lib/markdown";
import { readFile } from "@/api/files";
import { loadFailure } from "@/lib/utils";
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
    // Derive paths from the joined key so the memo recomputes only when the
    // set of paths changes, not on every new array identity.
    const paths = pathsKey === "" ? [] : pathsKey.split("|");
    const metas = paths.map((path) => {
      const fname = path.slice(DREAMER_PREFIX.length);
      return { path, fname, date: parseDreamFilename(fname) };
    });
    metas.sort((a, b) => {
      if (a.date && b.date) return b.date.getTime() - a.date.getTime();
      return b.fname.localeCompare(a.fname);
    });
    return metas;
  }, [pathsKey]);

  // The open page is keyed by the entry list, so a changed list starts from the newest dream.
  const [paging, setPaging] = useState({ key: pathsKey, page: 0 });
  const page = paging.key === pathsKey ? paging.page : 0;
  const setPage = (next: number) => {
    setPaging({ key: pathsKey, page: next });
  };

  const current = entries[page];
  const currentPath = current?.path ?? null;

  const dream = useResource(
    currentPath === null ? null : `${agent}\n${currentPath}`,
    async () => {
      if (currentPath === null) return "";
      const file = await readFile(agent, currentPath);
      return file.encoding === "utf-8" ? file.content : "";
    },
  );
  const content = dream.data;
  const error = loadFailure(dream.error, "read failed");

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
              no dreams yet. the agent journals nightly while you sleep
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
            onClick={() => setPage(Math.max(0, page - 1))}
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
            onClick={() => setPage(Math.min(entries.length - 1, page + 1))}
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
