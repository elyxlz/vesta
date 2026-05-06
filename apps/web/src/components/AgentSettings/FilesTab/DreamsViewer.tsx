import { useEffect, useState } from "react";
import { Moon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/lib/markdown";
import { readFile } from "@/api/files";
import { DREAMER_PREFIX, parseDreamFilename } from "./paths";

interface DreamsViewerProps {
  agent: string;
  dreamPaths: string[];
}

interface DreamEntry {
  path: string;
  fname: string;
  date: Date | null;
  content: string;
}

export function DreamsViewer({ agent, dreamPaths }: DreamsViewerProps) {
  const [entries, setEntries] = useState<DreamEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pathsKey = dreamPaths.join("|");

  useEffect(() => {
    let cancelled = false;
    setEntries(null);
    setError(null);

    if (dreamPaths.length === 0) {
      setEntries([]);
      return;
    }

    Promise.all(
      dreamPaths.map(async (path) => {
        const r = await readFile(agent, path);
        const fname = path.slice(DREAMER_PREFIX.length);
        return {
          path,
          fname,
          date: parseDreamFilename(fname),
          content: r.encoding === "utf-8" ? r.content : "",
        };
      }),
    )
      .then((results) => {
        if (cancelled) return;
        results.sort((a, b) => {
          if (a.date && b.date) return b.date.getTime() - a.date.getTime();
          return b.fname.localeCompare(a.fname);
        });
        setEntries(results);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent, pathsKey]);

  return (
    <div className="h-full overflow-auto bg-gradient-to-b from-background via-card to-muted/20">
      <div className="mx-auto max-w-2xl px-6 py-8">
        <header className="mb-8 flex items-center justify-center gap-2 text-muted-foreground">
          <Moon className="size-4" />
          <span className="font-serif text-sm italic tracking-wider uppercase">
            dream journal
          </span>
          <Moon className="size-4 -scale-x-100" />
        </header>

        {error ? (
          <p className="text-center text-sm text-destructive">
            failed to load: {error}
          </p>
        ) : entries === null ? (
          <div className="flex flex-col gap-6">
            <Skeleton className="h-32 w-full rounded-lg" />
            <Skeleton className="h-40 w-full rounded-lg" />
          </div>
        ) : entries.length === 0 ? (
          <p className="text-center font-serif text-sm italic text-muted-foreground/70">
            no dreams yet — the agent journals nightly while you sleep
          </p>
        ) : (
          <div className="flex flex-col gap-10">
            {entries.map((entry, i) => (
              <article key={entry.path}>
                {i > 0 && (
                  <div
                    className="my-6 flex items-center justify-center gap-2 text-muted-foreground/40"
                    aria-hidden
                  >
                    <span className="h-px w-8 bg-current" />
                    <span className="text-[10px]">·</span>
                    <span className="h-px w-8 bg-current" />
                  </div>
                )}
                <DreamEntryView entry={entry} />
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function DreamEntryView({ entry }: { entry: DreamEntry }) {
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
        <Markdown>{entry.content}</Markdown>
      </div>
    </>
  );
}
