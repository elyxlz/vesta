import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { apiFetch } from "@/lib/parent-bridge"
import {
  BookOpenIcon, XIcon, FilterIcon, RotateCcwIcon,
  ArrowDownAZIcon, ArrowDownZAIcon,
  CalendarArrowDownIcon, CalendarArrowUpIcon,
} from "lucide-react"
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover"

interface CatalogBook {
  filename: string
  title?: string
  author?: string
  cover?: string
  cover_b64?: string
  audio_file?: string | null
  word_count?: number
  subjects?: string[] | string
  date?: string
}

interface SortState {
  field: "title" | "date"
  dir: "asc" | "desc"
}

interface FilterState {
  author: string
  subject: string
  q: string
}

const EMPTY_FILTER: FilterState = { author: "", subject: "", q: "" }

interface SelectedState {
  filename: string | null
  position: number | null
  highlight: string | null
  updated_at: string | null
}

const POLL_MS = 4000

export default function LibraryPage() {
  const [catalog, setCatalog] = useState<CatalogBook[]>([])
  const [selected, setSelected] = useState<SelectedState | null>(null)
  const [text, setText] = useState<string>("")
  const [loadingText, setLoadingText] = useState(false)
  const [filter, setFilter] = useState<FilterState>(EMPTY_FILTER)
  const [filterOpen, setFilterOpen] = useState(false)
  const [sort, setSort] = useState<SortState>({ field: "title", dir: "asc" })
  const textRef = useRef<HTMLDivElement | null>(null)
  const lastUpdateRef = useRef<string | null>(null)

  // Load catalog once on mount.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const r = await apiFetch("library/catalog")
        if (cancelled || !r.ok) return
        const data = await r.json()
        setCatalog(Array.isArray(data) ? data : [])
      } catch {}
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Poll the selected book state so the page reflects changes from the agent.
  const pollSelected = useCallback(async () => {
    try {
      const r = await apiFetch("library/selected")
      if (!r.ok) return
      const data: SelectedState = await r.json()
      setSelected(data)
    } catch {}
  }, [])

  useEffect(() => {
    pollSelected()
    const t = setInterval(pollSelected, POLL_MS)
    return () => clearInterval(t)
  }, [pollSelected])

  // Fetch text when the selected file changes.
  useEffect(() => {
    if (!selected?.filename) {
      setText("")
      return
    }
    let cancelled = false
    ;(async () => {
      setLoadingText(true)
      try {
        const r = await apiFetch(`library/text/${encodeURIComponent(selected.filename!)}`)
        if (cancelled || !r.ok) return
        const body = await r.text()
        setText(body)
      } catch {}
      setLoadingText(false)
    })()
    return () => {
      cancelled = true
    }
  }, [selected?.filename])

  // Scroll to position/highlight whenever the selected update timestamp changes.
  useEffect(() => {
    if (!selected || selected.updated_at === lastUpdateRef.current) return
    lastUpdateRef.current = selected.updated_at
    const container = textRef.current
    if (!container) return
    requestAnimationFrame(() => {
      if (selected.highlight) {
        const mark = container.querySelector<HTMLElement>("mark[data-active='1']")
        mark?.scrollIntoView({ behavior: "smooth", block: "center" })
      } else if (typeof selected.position === "number") {
        const totalHeight = container.scrollHeight - container.clientHeight
        container.scrollTo({ top: totalHeight * selected.position, behavior: "smooth" })
      }
    })
  }, [selected, text])

  async function selectBook(book: CatalogBook | null) {
    try {
      await apiFetch("library/selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: book?.filename ?? null, position: null, highlight: null }),
      })
    } catch {}
    pollSelected()
  }

  const authors = useMemo(
    () => Array.from(new Set(catalog.map((b) => b.author).filter(Boolean) as string[])).sort(),
    [catalog],
  )
  const subjects = useMemo(() => {
    const s = new Set<string>()
    for (const b of catalog) {
      const subj = Array.isArray(b.subjects) ? b.subjects : b.subjects ? [b.subjects] : []
      subj.forEach((x) => s.add(x))
    }
    return Array.from(s).sort()
  }, [catalog])

  const activeFilters = [filter.author && "author", filter.subject && "subject", filter.q && "text"].filter(Boolean).length

  const filtered = useMemo(() => {
    const out = catalog.filter((b) => {
      if (filter.author && b.author !== filter.author) return false
      if (filter.subject) {
        const subj = Array.isArray(b.subjects) ? b.subjects : b.subjects ? [b.subjects] : []
        if (!subj.includes(filter.subject)) return false
      }
      if (filter.q) {
        const q = filter.q.toLowerCase()
        const hay = [b.title, b.author, b.filename].map((s) => s?.toLowerCase() ?? "")
        if (!hay.some((s) => s.includes(q))) return false
      }
      return true
    })
    const titleOf = (x: CatalogBook) => (x.title ?? x.filename).toLowerCase()
    const dateOf = (x: CatalogBook) => x.date ?? ""
    const flip = sort.dir === "desc" ? -1 : 1
    out.sort((a, b) => {
      if (sort.field === "date") {
        const cmp = dateOf(a).localeCompare(dateOf(b))
        if (cmp !== 0) return cmp * flip
        return titleOf(a).localeCompare(titleOf(b))
      }
      return titleOf(a).localeCompare(titleOf(b)) * flip
    })
    // return a fresh array reference so React definitely sees a change
    return [...out]
  }, [catalog, filter, sort.field, sort.dir])

  if (selected?.filename) {
    const book = catalog.find((b) => b.filename === selected.filename)
    return (
      <ReadingView
        selected={selected}
        book={book}
        text={text}
        loading={loadingText}
        onClose={() => selectBook(null)}
        textRef={textRef}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3 h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <BookOpenIcon className="size-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground font-medium">
            library ({filtered.length}{filtered.length !== catalog.length ? ` of ${catalog.length}` : ""})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-lg border overflow-hidden">
            <button
              onClick={() =>
                setSort((s) =>
                  s.field === "title"
                    ? { field: "title", dir: s.dir === "asc" ? "desc" : "asc" }
                    : { field: "title", dir: "asc" },
                )
              }
              className={`h-8 px-2 text-xs flex items-center gap-1 ${sort.field === "title" ? "bg-muted" : "hover:bg-muted/50"}`}
              title="sort by name"
            >
              {sort.field === "title" && sort.dir === "desc" ? (
                <ArrowDownZAIcon className="size-3" />
              ) : (
                <ArrowDownAZIcon className="size-3" />
              )}
              name
            </button>
            <button
              onClick={() =>
                setSort((s) =>
                  s.field === "date"
                    ? { field: "date", dir: s.dir === "asc" ? "desc" : "asc" }
                    : { field: "date", dir: "desc" },
                )
              }
              className={`h-8 px-2 text-xs flex items-center gap-1 border-l ${sort.field === "date" ? "bg-muted" : "hover:bg-muted/50"}`}
              title="sort by release date"
            >
              {sort.field === "date" && sort.dir === "asc" ? (
                <CalendarArrowUpIcon className="size-3" />
              ) : (
                <CalendarArrowDownIcon className="size-3" />
              )}
              date
            </button>
          </div>
          <Popover open={filterOpen} onOpenChange={setFilterOpen}>
            <PopoverTrigger asChild>
              <button className="h-8 px-2 text-xs rounded-lg border hover:bg-muted flex items-center gap-1">
                <FilterIcon className="size-3" />
                filter
                {activeFilters > 0 && (
                  <span className="ml-1 h-4 min-w-4 px-1 rounded-full bg-primary text-primary-foreground text-[9px] flex items-center justify-center">
                    {activeFilters}
                  </span>
                )}
              </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80">
              <FilterPanel
                filter={filter}
                onChange={(f) => {
                  setFilter(f)
                  setFilterOpen(false)
                }}
                authors={authors}
                subjects={subjects}
                onReset={() => {
                  setFilter(EMPTY_FILTER)
                  setFilterOpen(false)
                }}
              />
            </PopoverContent>
          </Popover>
        </div>
      </div>

      <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(120px,1fr))] overflow-y-auto flex-1 min-h-0 pb-2">
        {filtered.map((b) => (
          <BookCard
            key={b.title ?? b.filename}
            book={b}
            onSelect={() => selectBook(b)}
          />
        ))}
        {filtered.length === 0 && (
          <p className="text-xs text-muted-foreground col-span-full">no matches</p>
        )}
      </div>
    </div>
  )
}

function BookCard({ book, onSelect }: { book: CatalogBook; onSelect: () => void }) {
  // cover_b64 already includes the "data:image/jpeg;base64," prefix from the catalog.
  const coverSrc = book.cover_b64 || null
  return (
    <button
      onClick={onSelect}
      className="flex flex-col gap-1 rounded-2xl bg-muted p-2 text-left hover:bg-muted/70 transition"
    >
      <div className="aspect-[2/3] w-full overflow-hidden rounded-lg bg-background/40 flex items-center justify-center">
        {coverSrc ? (
          <img src={coverSrc} alt={book.title ?? book.filename} className="h-full w-full object-cover" />
        ) : (
          <BookOpenIcon className="size-6 text-muted-foreground/40" />
        )}
      </div>
      <span className="text-xs leading-tight line-clamp-2">{book.title ?? book.filename}</span>
      {book.author && <span className="text-[10px] text-muted-foreground line-clamp-1">{book.author}</span>}
    </button>
  )
}

function ReadingView({
  selected,
  book,
  text,
  loading,
  onClose,
  textRef,
}: {
  selected: SelectedState
  book: CatalogBook | undefined
  text: string
  loading: boolean
  onClose: () => void
  textRef: React.MutableRefObject<HTMLDivElement | null>
}) {
  const [fullCoverUrl, setFullCoverUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!book?.cover) return
    let cancelled = false
    let objectUrl: string | null = null
    ;(async () => {
      try {
        // catalog stores cover as "covers/<filename>.jpg"; /cover/<filename> serves it
        const name = book.cover!.replace(/^covers\//, "")
        const r = await apiFetch(`library/cover/${encodeURIComponent(name)}`)
        if (cancelled || !r.ok) return
        const blob = await r.blob()
        objectUrl = URL.createObjectURL(blob)
        setFullCoverUrl(objectUrl)
      } catch {}
    })()
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [book?.cover])
  // Render text with optional highlight. The highlight is a substring; all
  // case-insensitive matches get <mark>, the first one gets data-active='1'
  // so the scroll-into-view grabs it.
  let rendered: React.ReactNode = text
  if (selected.highlight && text) {
    const needle = selected.highlight
    const lowered = text.toLowerCase()
    const lowNeedle = needle.toLowerCase()
    const parts: React.ReactNode[] = []
    let cursor = 0
    let first = true
    while (cursor < text.length) {
      const idx = lowered.indexOf(lowNeedle, cursor)
      if (idx === -1) {
        parts.push(text.slice(cursor))
        break
      }
      if (idx > cursor) parts.push(text.slice(cursor, idx))
      parts.push(
        <mark
          key={idx}
          data-active={first ? "1" : undefined}
          className="bg-yellow-300/40 text-inherit rounded px-0.5"
        >
          {text.slice(idx, idx + needle.length)}
        </mark>,
      )
      first = false
      cursor = idx + needle.length
    }
    rendered = parts
  }

  return (
    <div className="flex flex-col gap-2 h-full">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <BookOpenIcon className="size-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs font-medium truncate">{selected.filename}</span>
        </div>
        <button
          onClick={onClose}
          className="h-10 px-4 text-sm rounded-lg border hover:bg-muted flex items-center gap-2 shrink-0"
        >
          <XIcon className="size-4" />
          close
        </button>
      </div>
      {selected.highlight && (
        <p className="text-[10px] text-muted-foreground px-1">jumped to: "{selected.highlight.slice(0, 80)}{selected.highlight.length > 80 ? "..." : ""}"</p>
      )}
      <div
        ref={textRef}
        className="rounded-2xl bg-muted p-3 overflow-y-auto flex-1 min-h-0 text-sm whitespace-pre-wrap leading-relaxed"
      >
        {(fullCoverUrl || book?.cover_b64) && (
          <div className="flex flex-col items-center gap-2 mb-4 pb-4 border-b border-muted-foreground/15">
            <img
              src={fullCoverUrl ?? book?.cover_b64 ?? ""}
              alt={book?.title ?? selected.filename ?? ""}
              className="max-h-[480px] rounded-lg shadow-sm"
            />
            {book?.title && <h2 className="text-base font-semibold text-center">{book.title}</h2>}
            {book?.author && <p className="text-xs text-muted-foreground">{book.author}</p>}
          </div>
        )}
        {loading ? <span className="text-xs text-muted-foreground">loading...</span> : rendered}
      </div>
    </div>
  )
}

function FilterPanel({
  filter,
  onChange,
  authors,
  subjects,
  onReset,
}: {
  filter: FilterState
  onChange: (f: FilterState) => void
  authors: string[]
  subjects: string[]
  onReset: () => void
}) {
  const [local, setLocal] = useState<FilterState>(filter)

  useEffect(() => {
    setLocal(filter)
  }, [filter])

  return (
    <div className="flex flex-col gap-3 text-sm">
      <div className="font-medium flex items-center gap-1.5">
        <FilterIcon className="size-3.5" />
        filter books
      </div>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">author</span>
        <select
          value={local.author}
          onChange={(e) => setLocal({ ...local, author: e.target.value })}
          className="h-9 text-xs rounded-lg border bg-background px-2 max-w-full truncate"
        >
          <option value="">any</option>
          {authors.map((a) => {
            const display = a.length > 40 ? a.slice(0, 40) + "…" : a
            return (
              <option key={a} value={a}>{display}</option>
            )
          })}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">subject</span>
        <select
          value={local.subject}
          onChange={(e) => setLocal({ ...local, subject: e.target.value })}
          className="h-9 text-xs rounded-lg border bg-background px-2 max-w-full truncate"
        >
          <option value="">any</option>
          {subjects.map((s) => {
            const display = s.length > 40 ? s.slice(0, 40) + "…" : s
            return (
              <option key={s} value={s}>{display}</option>
            )
          })}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-[10px] text-muted-foreground">free search</span>
        <input
          type="text"
          value={local.q}
          onChange={(e) => setLocal({ ...local, q: e.target.value })}
          placeholder="title, author, filename..."
          className="h-9 text-xs rounded-lg border bg-background px-2"
        />
      </label>

      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          onClick={() => {
            onReset()
            setLocal(EMPTY_FILTER)
          }}
          className="h-9 px-3 text-xs rounded-lg border hover:bg-muted flex items-center gap-1"
        >
          <RotateCcwIcon className="size-3" />
          reset
        </button>
        <button
          onClick={() => onChange(local)}
          className="h-9 px-3 text-xs rounded-lg bg-primary text-primary-foreground hover:opacity-90"
        >
          apply
        </button>
      </div>
    </div>
  )
}
