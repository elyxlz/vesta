import { useEffect, useMemo, useState } from "react";
import {
  BookOpen,
  ChevronLeft,
  ChevronRight,
  FileText,
  Moon,
  ScrollText,
  Sparkles,
  Wand2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { FileTreeEntry } from "@/api/files";
import { HostAccessCard } from "../HostAccessCard";
import {
  collectDreamPaths,
  CONSTITUTION_PATH,
  MEMORY_PATH,
  SKILLS_PREFIX,
} from "./paths";

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
    <div className="flex h-full min-h-0 flex-col gap-3 p-1">
      <GroupLabel>vesta's mind</GroupLabel>
      <MindCard
        memorySelected={selected === MEMORY_PATH && !dreamsActive}
        constitutionSelected={selected === CONSTITUTION_PATH && !dreamsActive}
        dreamsActive={dreamsActive}
        dreamCount={dreamCount}
        onSelectMemory={() => onSelect(MEMORY_PATH)}
        onSelectConstitution={() => onSelect(CONSTITUTION_PATH)}
        onShowDreams={onShowDreams}
      />
      <SkillsCard skills={skills} selected={selected} onSelect={onSelect} />
      <GroupLabel className="pt-1">on this computer</GroupLabel>
      <div className="shrink-0">
        <HostAccessCard />
      </div>
    </div>
  );
}

function GroupLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <p
      className={cn(
        "shrink-0 px-1 text-[11px] font-medium text-muted-foreground/70",
        className,
      )}
    >
      {children}
    </p>
  );
}

function MindCard({
  memorySelected,
  constitutionSelected,
  dreamsActive,
  dreamCount,
  onSelectMemory,
  onSelectConstitution,
  onShowDreams,
}: {
  memorySelected: boolean;
  constitutionSelected: boolean;
  dreamsActive: boolean;
  dreamCount: number;
  onSelectMemory: () => void;
  onSelectConstitution: () => void;
  onShowDreams: () => void;
}) {
  return (
    <Card size="sm" className="shrink-0">
      <CardContent className="flex flex-col gap-1.5">
        <HubRow
          onClick={onSelectMemory}
          selected={memorySelected}
          iconClass="bg-amber-500/12 text-amber-600 dark:text-amber-400"
          icon={<BookOpen className="size-[18px]" />}
          title="memory"
          description="what vesta remembers about you"
        />
        <HubRow
          onClick={onSelectConstitution}
          selected={constitutionSelected}
          iconClass="bg-emerald-500/12 text-emerald-600 dark:text-emerald-400"
          icon={<ScrollText className="size-[18px]" />}
          title="constitution"
          description="the directives you set that vesta follows"
        />
        <HubRow
          onClick={onShowDreams}
          selected={dreamsActive}
          iconClass="bg-indigo-500/12 text-indigo-500 dark:text-indigo-400"
          icon={<Moon className="size-[18px]" />}
          title="dreams"
          description="nightly reflections on the day"
          trailing={
            <div className="flex items-center gap-1.5">
              {dreamCount > 0 && (
                <span className="text-[11px] text-muted-foreground">
                  {dreamCount}
                </span>
              )}
              <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
            </div>
          }
        />
      </CardContent>
    </Card>
  );
}

// A soft, tappable "cell" inside a hub card: a tinted icon square, a title,
// an optional secondary line, and optional trailing content.
function HubRow({
  icon,
  iconClass,
  title,
  description,
  trailing,
  selected = false,
  onClick,
}: {
  icon: React.ReactNode;
  iconClass: string;
  title: string;
  description?: string;
  trailing?: React.ReactNode;
  selected?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex w-full items-center gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors",
        selected ? "bg-muted" : "bg-muted/40 hover:bg-muted/70 active:bg-muted",
      )}
    >
      <span
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-[10px]",
          iconClass,
        )}
      >
        {icon}
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-medium leading-tight">{title}</span>
        {description ? (
          <span className="truncate text-[11px] text-muted-foreground">
            {description}
          </span>
        ) : null}
      </span>
      {trailing}
    </button>
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
    if (nav.view === "skill" && !skills.some((s) => s.path === nav.skillPath)) {
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

      <CardContent className="flex flex-1 min-h-0 flex-col gap-1.5 overflow-auto">
        {inSkillView && activeSkill ? (
          activeSkill.mdFiles.length === 0 ? (
            <EmptyRow>no markdown files</EmptyRow>
          ) : (
            activeSkill.mdFiles.map((file) => (
              <Row
                key={file.path}
                icon={<FileText className="size-4" />}
                iconClass="bg-muted text-muted-foreground"
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
              iconClass="bg-violet-500/12 text-violet-600 dark:text-violet-400"
              label={skill.name}
              hasChevron
              selected={
                selected !== null && selected.startsWith(`${skill.path}/`)
              }
              onClick={() => setNav({ view: "skill", skillPath: skill.path })}
            />
          ))
        )}
      </CardContent>
    </Card>
  );
}

function Row({
  icon,
  iconClass,
  label,
  hasChevron = false,
  selected,
  onClick,
}: {
  icon: React.ReactNode;
  iconClass: string;
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
        "flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-left text-sm transition-colors",
        selected ? "bg-muted" : "bg-muted/40 hover:bg-muted/70 active:bg-muted",
      )}
    >
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-[9px]",
          iconClass,
        )}
      >
        {icon}
      </span>
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
