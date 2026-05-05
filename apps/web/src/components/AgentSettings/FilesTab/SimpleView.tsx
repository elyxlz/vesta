import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileText,
  Moon,
  Sparkles,
  Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { FileTreeEntry } from "@/api/files";
import { collectDreamPaths, MEMORY_PATH, SKILLS_PREFIX } from "./paths";

interface SimpleViewProps {
  entries: FileTreeEntry[];
  selected: string | null;
  dreamsActive: boolean;
  onSelect: (path: string) => void;
  onShowDreams: () => void;
}

interface Skill {
  name: string;
  path: string;
  mdFiles: { name: string; path: string }[];
}

type SkillNav = { view: "root" } | { view: "skill"; skillPath: string };

function collectSkills(entries: FileTreeEntry[]): Skill[] {
  return entries
    .filter(
      (e) =>
        e.is_dir &&
        e.path.startsWith(SKILLS_PREFIX) &&
        !e.path.slice(SKILLS_PREFIX.length).includes("/"),
    )
    .map((e) => ({
      name: e.path.slice(SKILLS_PREFIX.length),
      path: e.path,
      mdFiles: entries
        .filter(
          (f) =>
            !f.is_dir &&
            f.path.startsWith(`${e.path}/`) &&
            f.path.endsWith(".md"),
        )
        .map((f) => ({ name: f.path.slice(e.path.length + 1), path: f.path }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function SimpleView({
  entries,
  selected,
  dreamsActive,
  onSelect,
  onShowDreams,
}: SimpleViewProps) {
  const skills = useMemo(() => collectSkills(entries), [entries]);
  const dreamCount = useMemo(
    () => collectDreamPaths(entries).length,
    [entries],
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 p-1">
      <MindCard
        memorySelected={selected === MEMORY_PATH && !dreamsActive}
        dreamsActive={dreamsActive}
        dreamCount={dreamCount}
        onSelectMemory={() => onSelect(MEMORY_PATH)}
        onShowDreams={onShowDreams}
      />
      <SkillsCard skills={skills} selected={selected} onSelect={onSelect} />
    </div>
  );
}

function MindCard({
  memorySelected,
  dreamsActive,
  dreamCount,
  onSelectMemory,
  onShowDreams,
}: {
  memorySelected: boolean;
  dreamsActive: boolean;
  dreamCount: number;
  onSelectMemory: () => void;
  onShowDreams: () => void;
}) {
  return (
    <Card size="sm" className="!py-0 !gap-0 flex shrink-0 flex-col">
      <button
        type="button"
        onClick={onSelectMemory}
        className={cn(
          "flex w-full items-center gap-2.5 border-b border-border/60 px-4 py-3 text-left text-sm transition-colors",
          memorySelected
            ? "bg-muted text-foreground"
            : "hover:bg-muted/60 active:bg-muted",
        )}
      >
        <BookOpen className="size-4 text-muted-foreground" />
        <span className="font-medium">memory</span>
      </button>

      <button
        type="button"
        onClick={onShowDreams}
        className={cn(
          "flex w-full items-center gap-2.5 px-4 py-3 text-left text-sm transition-colors",
          dreamsActive
            ? "bg-muted text-foreground"
            : "hover:bg-muted/60 active:bg-muted",
        )}
      >
        <Moon className="size-4 text-muted-foreground" />
        <span className="font-medium">dreams</span>
        {dreamCount > 0 && (
          <span className="text-[10px] text-muted-foreground/60">
            {dreamCount}
          </span>
        )}
        <ChevronRight className="ml-auto size-4 shrink-0 text-muted-foreground/60" />
      </button>
    </Card>
  );
}

function SkillsCard({
  skills,
  selected,
  onSelect,
}: {
  skills: Skill[];
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  const [nav, setNav] = useState<SkillNav>(() => {
    if (selected && selected.startsWith(SKILLS_PREFIX)) {
      const skillName = selected.slice(SKILLS_PREFIX.length).split("/")[0];
      const skill = skills.find((s) => s.name === skillName);
      if (skill) return { view: "skill", skillPath: skill.path };
    }
    return { view: "root" };
  });

  useEffect(() => {
    if (
      nav.view === "skill" &&
      !skills.some((s) => s.path === nav.skillPath)
    ) {
      setNav({ view: "root" });
    }
  }, [skills, nav]);

  const activeSkill =
    nav.view === "skill"
      ? (skills.find((s) => s.path === nav.skillPath) ?? null)
      : null;
  const inSkillView = activeSkill !== null;

  return (
    <Card size="sm" className="!py-0 !gap-0 flex flex-1 min-h-0 flex-col">
      <CardHeader className="shrink-0 !flex !flex-row !items-center !gap-2.5 !px-5 !py-2.5 border-b border-border/60 [.border-b]:!pb-2.5">
        {inSkillView && activeSkill ? (
          <>
            <button
              type="button"
              onClick={() => setNav({ view: "root" })}
              className="flex items-center gap-0.5 text-sm hover:opacity-80"
            >
              <ChevronLeft className="size-4" />
              skills
            </button>
            <span className="text-muted-foreground/60">/</span>
            <CardTitle className="!text-sm !font-medium truncate">
              {activeSkill.name}
            </CardTitle>
          </>
        ) : (
          <>
            <Sparkles className="size-4 text-muted-foreground" />
            <CardTitle className="!text-sm !font-medium">skills</CardTitle>
          </>
        )}
      </CardHeader>

      <CardContent className="flex-1 min-h-0 overflow-auto !px-0">
        {inSkillView && activeSkill ? (
          activeSkill.mdFiles.length === 0 ? (
            <EmptyRow>no markdown files</EmptyRow>
          ) : (
            activeSkill.mdFiles.map((file) => (
              <Row
                key={file.path}
                icon={<FileText className="size-4" />}
                label={file.name}
                selected={selected === file.path}
                onClick={() => onSelect(file.path)}
              />
            ))
          )
        ) : skills.length === 0 ? (
          <EmptyRow>no skills installed</EmptyRow>
        ) : (
          skills.map((skill) => (
            <Row
              key={skill.path}
              icon={<Wand2 className="size-4" />}
              label={skill.name}
              hasChevron
              selected={
                selected !== null && selected.startsWith(`${skill.path}/`)
              }
              onClick={() =>
                setNav({ view: "skill", skillPath: skill.path })
              }
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}

function Row({
  icon,
  label,
  hasChevron = false,
  selected,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  hasChevron?: boolean;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-2.5 border-b border-border/60 px-4 py-2.5 text-left text-sm transition-colors last:border-b-0",
        selected
          ? "bg-muted text-foreground"
          : "hover:bg-muted/60 active:bg-muted",
      )}
    >
      <span className="text-muted-foreground">{icon}</span>
      <span className="flex-1 truncate">{label}</span>
      {hasChevron && (
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
      )}
    </button>
  );
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-4 py-2.5 text-xs italic text-muted-foreground/70">
      {children}
    </p>
  );
}
