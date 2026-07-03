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
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
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
    <div className="flex flex-col gap-3 p-1">
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
      <CardContent>
        <ItemGroup>
          <HubRow
            onClick={onSelectMemory}
            selected={memorySelected}
            iconClass="bg-amber-500/12 text-amber-600 dark:text-amber-400"
            icon={<BookOpen />}
            title="memory"
            description="what vesta remembers about you"
          />
          <HubRow
            onClick={onSelectConstitution}
            selected={constitutionSelected}
            iconClass="bg-emerald-500/12 text-emerald-600 dark:text-emerald-400"
            icon={<ScrollText />}
            title="constitution"
            description="the directives you set that vesta follows"
          />
          <HubRow
            onClick={onShowDreams}
            selected={dreamsActive}
            iconClass="bg-indigo-500/12 text-indigo-500 dark:text-indigo-400"
            icon={<Moon />}
            title="dreams"
            description="nightly reflections on the day"
            trailing={
              <>
                {dreamCount > 0 && (
                  <span className="text-[11px] text-muted-foreground">
                    {dreamCount}
                  </span>
                )}
                <ChevronRight className="size-4 text-muted-foreground/60" />
              </>
            }
          />
        </ItemGroup>
      </CardContent>
    </Card>
  );
}

// A soft, tappable "cell" inside a hub card, built on the shadcn Item primitive:
// a tinted icon square, a title, an optional secondary line, optional trailing.
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
    <Item
      asChild
      variant="muted"
      size="sm"
      className={cn(
        "cursor-pointer text-left hover:bg-muted/70",
        selected && "bg-muted",
      )}
    >
      <button type="button" onClick={onClick}>
        <ItemMedia
          variant="icon"
          className={cn("size-9 rounded-[10px]", iconClass)}
        >
          {icon}
        </ItemMedia>
        <ItemContent className="gap-0.5">
          <ItemTitle>{title}</ItemTitle>
          {description ? (
            <ItemDescription className="text-[11px]">
              {description}
            </ItemDescription>
          ) : null}
        </ItemContent>
        {trailing ? <ItemActions>{trailing}</ItemActions> : null}
      </button>
    </Item>
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
    <Card size="sm" className="!py-0 !gap-0 flex flex-col">
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

      <CardContent className="max-h-80 overflow-auto py-2">
        {inSkillView && activeSkill ? (
          activeSkill.mdFiles.length === 0 ? (
            <EmptyRow>no markdown files</EmptyRow>
          ) : (
            <ItemGroup>
              {activeSkill.mdFiles.map((file) => (
                <Row
                  key={file.path}
                  icon={<FileText />}
                  iconClass="bg-muted text-muted-foreground"
                  label={file.name}
                  selected={selected === file.path}
                  onClick={() => onSelect(file.path)}
                />
              ))}
            </ItemGroup>
          )
        ) : skills.length === 0 ? (
          <EmptyRow>no skills installed</EmptyRow>
        ) : (
          <ItemGroup>
            {skills.map((skill) => (
              <Row
                key={skill.path}
                icon={<Wand2 />}
                iconClass="bg-violet-500/12 text-violet-600 dark:text-violet-400"
                label={skill.name}
                hasChevron
                selected={
                  selected !== null && selected.startsWith(`${skill.path}/`)
                }
                onClick={() => setNav({ view: "skill", skillPath: skill.path })}
              />
            ))}
          </ItemGroup>
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
    <Item
      asChild
      variant="muted"
      size="sm"
      className={cn(
        "cursor-pointer text-left hover:bg-muted/70",
        selected && "bg-muted",
      )}
    >
      <button type="button" onClick={onClick}>
        <ItemMedia
          variant="icon"
          className={cn("size-8 rounded-[9px]", iconClass)}
        >
          {icon}
        </ItemMedia>
        <ItemContent>
          <ItemTitle>{label}</ItemTitle>
        </ItemContent>
        {hasChevron ? (
          <ItemActions>
            <ChevronRight className="size-4 text-muted-foreground/60" />
          </ItemActions>
        ) : null}
      </button>
    </Item>
  );
}

function EmptyRow({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-4 py-2.5 text-xs italic text-muted-foreground/70">
      {children}
    </p>
  );
}
