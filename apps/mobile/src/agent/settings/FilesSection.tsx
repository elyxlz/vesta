import { useMemo, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { fetchFileTree } from "@/api/endpoints";
import type { FileTreeEntry } from "@/api/types";
import { useAgent } from "@/agent/AgentProvider";
import { FormRow, FormSection, SwitchRow } from "@/components/ui/Form";
import { ErrorState, LoadingState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";

const memoryPath = "/root/agent/MEMORY.md";
const constitutionPath = "/root/agent/constitution.md";
const skillsPrefix = "/root/agent/skills/";
const dreamsPrefix = "/root/agent/dreamer/";

interface FileGroup {
  name: string;
  files: FileTreeEntry[];
}

function displayName(path: string): string {
  const parts = path.split("/").filter(Boolean);
  return parts.at(-1) ?? path;
}

function groupSkills(entries: FileTreeEntry[]): FileGroup[] {
  const groups = new Map<string, FileTreeEntry[]>();
  for (const entry of entries) {
    if (entry.is_dir || !entry.path.startsWith(skillsPrefix) || !entry.path.endsWith(".md")) continue;
    const relative = entry.path.slice(skillsPrefix.length);
    const skillName = relative.split("/")[0];
    if (!skillName) continue;
    const current = groups.get(skillName) ?? [];
    current.push(entry);
    groups.set(skillName, current);
  }
  return [...groups.entries()]
    .map(([name, files]) => ({ name, files: files.sort((a, b) => a.path.localeCompare(b.path)) }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function FilesSection() {
  const router = useRouter();
  const { api } = useSession();
  const { name } = useAgent();
  const { colors } = usePreferences();
  const [advanced, setAdvanced] = useState(false);
  const [openSkill, setOpenSkill] = useState<string | null>(null);
  const tree = useQuery({
    queryKey: ["file-tree", name],
    queryFn: () => fetchFileTree(api, name),
  });
  const skills = useMemo(() => groupSkills(tree.data ?? []), [tree.data]);
  const dreams = useMemo(
    () => (tree.data ?? [])
      .filter((entry) => !entry.is_dir && entry.path.startsWith(dreamsPrefix) && entry.path.endsWith(".md"))
      .sort((a, b) => b.path.localeCompare(a.path)),
    [tree.data],
  );

  if (tree.isLoading) return <LoadingState label="Loading agent files…" />;
  if (!tree.data) {
    return <ErrorState message="Agent files are unavailable." retry={() => void tree.refetch()} />;
  }

  const openFile = (path: string) => {
    router.push({
      pathname: "/agent/[name]/file",
      params: { name, path },
    });
  };
  const byPath = new Map(tree.data.map((entry) => [entry.path, entry]));

  if (advanced) {
    return (
      <>
        <FormSection title="File browser" footer="Advanced view exposes the complete agent filesystem returned by the gateway.">
          <SwitchRow label="Advanced view" value onValueChange={setAdvanced} />
        </FormSection>
        <FormSection title={`${tree.data.length} entries`}>
          {[...tree.data]
            .sort((a, b) => a.path.localeCompare(b.path))
            .map((entry) => (
              <FormRow
                key={entry.path}
                label={displayName(entry.path)}
                detail={entry.path}
                icon={entry.is_dir ? "folder-outline" : "document-text-outline"}
                onPress={entry.is_dir ? undefined : () => openFile(entry.path)}
              />
            ))}
        </FormSection>
      </>
    );
  }

  return (
    <>
      <FormSection title="View">
        <SwitchRow label="Advanced view" detail="Show every file and folder path." value={false} onValueChange={setAdvanced} />
      </FormSection>
      <FormSection title={`Who ${name} is`}>
        <FormRow
          label="Memory"
          detail={`What ${name} remembers about you.`}
          icon="book-outline"
          value={byPath.has(memoryPath) ? undefined : "missing"}
          onPress={byPath.has(memoryPath) ? () => openFile(memoryPath) : undefined}
        />
        <FormRow
          label="Constitution"
          detail={`The directives ${name} follows.`}
          icon="reader-outline"
          value={byPath.has(constitutionPath) ? undefined : "missing"}
          onPress={byPath.has(constitutionPath) ? () => openFile(constitutionPath) : undefined}
        />
      </FormSection>
      <FormSection title="Dreams" footer="Nightly reflections are read-only unless the gateway reports a writable file.">
        {dreams.slice(0, 30).map((entry) => (
          <FormRow
            key={entry.path}
            label={displayName(entry.path).replace(".md", "").replace("T", " at ")}
            icon="moon-outline"
            onPress={() => openFile(entry.path)}
          />
        ))}
        {dreams.length === 0 ? <FormRow label="No dreams recorded yet" icon="moon-outline" /> : null}
      </FormSection>
      <FormSection title="Abilities">
        {skills.map((skill) => (
          <View key={skill.name}>
            <FormRow
              label={skill.name}
              detail={`${skill.files.length} Markdown ${skill.files.length === 1 ? "file" : "files"}`}
              icon="color-wand-outline"
              value={openSkill === skill.name ? "hide" : "open"}
              onPress={() => setOpenSkill((current) => current === skill.name ? null : skill.name)}
            />
            {openSkill === skill.name ? (
              <View style={[styles.skillFiles, { borderLeftColor: colors.border }]}>
                {skill.files.map((entry) => (
                  <FormRow
                    key={entry.path}
                    label={entry.path.slice(`${skillsPrefix}${skill.name}/`.length)}
                    icon="document-text-outline"
                    onPress={() => openFile(entry.path)}
                  />
                ))}
              </View>
            ) : null}
          </View>
        ))}
        {skills.length === 0 ? <FormRow label="No skills installed" icon="color-wand-outline" /> : null}
      </FormSection>
      <Text style={[styles.note, { color: colors.secondaryText }]}>Shared host folders are managed separately under Host access.</Text>
    </>
  );
}

const styles = StyleSheet.create({
  skillFiles: { marginLeft: 30, borderLeftWidth: StyleSheet.hairlineWidth },
  note: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16 },
});
