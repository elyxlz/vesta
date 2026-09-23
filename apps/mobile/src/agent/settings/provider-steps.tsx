import { useState, type ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import Stack from "expo-router/stack";
import * as Haptics from "expo-haptics";
import type {
  ProviderCatalog,
  ProviderContextPreset,
  ProviderKind,
} from "@vesta/core";
import {
  CLAUDE_ALIAS_OPTIONS,
  sortAdvertisedProviders,
  type ModelOption,
} from "@/agent/settings/provider-model";
import { Screen } from "@/components/layout/Screen";
import { LoadingSpinner } from "@/components/loading-spinner";
import { ProviderLogo } from "@/components/ProviderLogo";
import { SheetChrome } from "@/components/sheet-chrome";
import { SheetTitle } from "@/components/sheet-title";
import { Button } from "@/components/ui/Button";
import { Field, FormRow, FormSection } from "@/components/ui/Form";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_IOS = process.env.EXPO_OS === "ios";

const PROVIDER_TAGLINES: Record<ProviderKind, string> = {
  claude: "Sign in with your Claude plan",
  openrouter: "Pay per token with an API key",
  zai: "Use your GLM Coding Plan",
  kimi: "Use your Kimi membership",
  openai: "Sign in with your ChatGPT plan",
};

// A pushed step in the settings stack. iOS draws the title and the back chevron natively;
// Android sheets have no native header, so SheetChrome stands in.
export function ProviderStepScreen({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <>
      {IS_IOS ? <SheetTitle>{title}</SheetTitle> : null}
      <SheetChrome title={title} closeLabel="Back" />
      <Screen contentStyle={styles.content}>{children}</Screen>
    </>
  );
}

export function StepIntro({
  kind,
  children,
}: {
  kind: ProviderKind;
  children: string;
}) {
  const { colors } = usePreferences();
  return (
    <View style={styles.intro}>
      <ProviderLogo kind={kind} size={40} />
      <Text style={[styles.introText, { color: colors.secondaryText }]}>
        {children}
      </Text>
    </View>
  );
}

// The step's one forward action: a prominent header button on iOS, a button under the form on
// Android, whose sheets carry no native header.
export function StepAction({
  children,
  disabled = false,
  busy = false,
  onPress,
}: {
  children: string;
  disabled?: boolean;
  busy?: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  if (IS_IOS) {
    return (
      <Stack.Toolbar placement="right">
        <Stack.Toolbar.Button
          variant="prominent"
          tintColor={colors.accent}
          disabled={disabled || busy}
          onPress={onPress}
        >
          {children}
        </Stack.Toolbar.Button>
      </Stack.Toolbar>
    );
  }
  return (
    <Button size="large" disabled={disabled} loading={busy} onPress={onPress}>
      {children}
    </Button>
  );
}

function choose(onPick: () => void) {
  void Haptics.selectionAsync();
  onPick();
}

export function ProviderChoiceList({
  catalog,
  onPick,
}: {
  catalog: ProviderCatalog;
  onPick: (kind: ProviderKind) => void;
}) {
  return (
    <FormSection footer="The service that powers this agent.">
      {sortAdvertisedProviders(catalog.providers).map((kind) => (
        <FormRow
          key={kind}
          leading={<ProviderLogo kind={kind} size={24} />}
          label={catalog.providers[kind]?.display ?? kind}
          detail={PROVIDER_TAGLINES[kind]}
          onPress={() => choose(() => onPick(kind))}
        />
      ))}
    </FormSection>
  );
}

// A pick-one row: the checkmark marks the current choice, and a spinner marks the one being
// applied, so every other row waits.
function PickRows({
  options,
  selected,
  pending,
  onPick,
}: {
  options: readonly { value: string; label: string; detail?: string }[];
  selected: string;
  pending: string | null;
  onPick: (value: string) => void;
}) {
  const { colors } = usePreferences();
  return options.map((option) => (
    <FormRow
      key={option.value}
      label={option.label}
      detail={option.detail}
      selected={pending === null ? option.value === selected : false}
      trailing={
        pending === option.value ? (
          <LoadingSpinner color={colors.secondaryText} />
        ) : undefined
      }
      onPress={
        pending === null ? () => choose(() => onPick(option.value)) : undefined
      }
    />
  ));
}

function matchesQuery(option: ModelOption, query: string): boolean {
  const needle = query.trim().toLowerCase();
  return (
    option.label.toLowerCase().includes(needle) ||
    option.value.toLowerCase().includes(needle)
  );
}

// Claude offers its two aliases first and the live catalog behind a toggle; OpenRouter's long
// live list is searchable from the native header search bar; a fixed catalog is a plain list.
export function ModelList({
  kind,
  options,
  loading,
  selected,
  pending,
  onPick,
}: {
  kind: ProviderKind;
  options: readonly ModelOption[];
  loading: boolean;
  selected: string;
  pending: string | null;
  onPick: (model: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [showAll, setShowAll] = useState(false);
  const loadingRow = loading ? <FormRow label="Loading models…" /> : null;

  if (kind === "claude") {
    return (
      <>
        <FormSection>
          <PickRows
            options={CLAUDE_ALIAS_OPTIONS}
            selected={selected}
            pending={pending}
            onPick={onPick}
          />
        </FormSection>
        <FormSection footer="Opus and Sonnet always run the newest release.">
          <FormRow
            label="All models"
            expanded={showAll}
            onPress={() => setShowAll(!showAll)}
          />
          {showAll ? (
            <>
              {loadingRow}
              <PickRows
                options={options}
                selected={selected}
                pending={pending}
                onPick={onPick}
              />
            </>
          ) : null}
        </FormSection>
      </>
    );
  }

  const searchable = kind === "openrouter";
  return (
    <>
      {searchable && IS_IOS ? (
        <Stack.SearchBar
          placeholder="Search models"
          autoCapitalize="none"
          hideWhenScrolling={false}
          onChangeText={(event) => setQuery(event.nativeEvent.text)}
          onCancelButtonPress={() => setQuery("")}
        />
      ) : null}
      {searchable && !IS_IOS ? (
        <Field
          placeholder="Search models"
          value={query}
          onChangeText={setQuery}
          autoCapitalize="none"
          autoCorrect={false}
        />
      ) : null}
      <FormSection
        footer={
          searchable ? "The top models on OpenRouter this week." : undefined
        }
      >
        {loadingRow}
        <PickRows
          options={options.filter((option) => matchesQuery(option, query))}
          selected={selected}
          pending={pending}
          onPick={onPick}
        />
      </FormSection>
    </>
  );
}

export function ContextList({
  presets,
  selected,
  pending,
  onPick,
}: {
  presets: readonly ProviderContextPreset[];
  selected: number;
  pending: number | null;
  onPick: (tokens: number) => void;
}) {
  return (
    <FormSection footer="How much this agent keeps in mind. More remembers more and costs more.">
      <PickRows
        options={presets.map((preset) => ({
          value: String(preset.tokens),
          label: preset.label,
          detail: preset.note,
        }))}
        selected={String(selected)}
        pending={pending === null ? null : String(pending)}
        onPick={(value) => onPick(Number(value))}
      />
    </FormSection>
  );
}

const styles = StyleSheet.create({
  content: { gap: 24, paddingBottom: 80 },
  intro: { alignItems: "center", gap: 12, paddingVertical: 8 },
  introText: { fontSize: 15, lineHeight: 21, textAlign: "center" },
});
