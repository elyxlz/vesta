import { useEffect, useRef, useState } from "react";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import type { VoiceDomain } from "@vesta/core";
import { setVoiceSetting, type SettingDef } from "@/lib/voice";
import { CollapsibleChevronButton } from "./collapsible-chevron-button";
import { useOptimisticToggle } from "./use-optimistic-toggle";
import { VoicePicker } from "./voice-picker";

export function DynamicSettings({
  settings,
  domain,
  agentName,
  onSettingChange,
}: {
  settings: SettingDef[];
  domain: VoiceDomain;
  agentName: string | null;
  onSettingChange: (settings: SettingDef[]) => void;
}) {
  const updateSetting = (key: string, value: unknown) => {
    if (agentName) {
      setVoiceSetting(agentName, domain, key, value)
        .then((status) => {
          if (status.settings) onSettingChange(status.settings);
        })
        .catch(console.warn);
    }
  };

  return (
    <>
      {settings.map((s) => (
        <SettingByType key={s.key} setting={s} updateSetting={updateSetting} />
      ))}
    </>
  );
}

function SettingByType({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const control = (() => {
    switch (setting.type) {
      case "bool":
        return <BoolSetting setting={setting} updateSetting={updateSetting} />;
      case "number":
        return (
          <NumberSetting setting={setting} updateSetting={updateSetting} />
        );
      case "select":
        return (
          <SelectSetting setting={setting} updateSetting={updateSetting} />
        );
      case "text":
        return <TextSetting setting={setting} updateSetting={updateSetting} />;
      default:
        return null;
    }
  })();
  if (!control) return null;
  return (
    <>
      {control}
      <SubSettingsCollapsible setting={setting} updateSetting={updateSetting} />
    </>
  );
}

function SubSettingsCollapsible({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const items = setting.config;
  if (!items?.length) return null;
  const label = setting.config_label ?? "configuration";
  return (
    <Collapsible>
      <CollapsibleChevronButton>{label}</CollapsibleChevronButton>
      <CollapsibleContent>
        <div className="flex flex-col gap-3 pt-2 px-6">
          {items.map((child) => (
            <SettingByType
              key={child.key}
              setting={child}
              updateSetting={updateSetting}
            />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

// --- Individual setting renderers ---

function BoolSetting({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const [value, toggle] = useOptimisticToggle(
    typeof setting.value === "boolean" ? setting.value : undefined,
    typeof setting.default === "boolean" ? setting.default : false,
    (v) => updateSetting(setting.key, v),
  );
  return (
    <Field orientation="horizontal" className="items-center justify-between">
      <FieldContent>
        <FieldLabel className="text-base">{setting.label}</FieldLabel>
        {setting.description && (
          <FieldDescription>{setting.description}</FieldDescription>
        )}
      </FieldContent>
      <Switch checked={value} onCheckedChange={toggle} />
    </Field>
  );
}

function NumberSetting({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const serverValue =
    typeof setting.value === "number"
      ? setting.value
      : typeof setting.default === "number"
        ? setting.default
        : 0;
  // The pending edit, keyed by the server value it was made against, so a server change
  // (another client, a reload) shows through instead of being reset from an effect.
  const [edit, setEdit] = useState<{ base: number; value: number } | null>(
    null,
  );
  const localValue =
    edit !== null && edit.base === serverValue ? edit.value : serverValue;
  const setLocalValue = (value: number) => {
    setEdit({ base: serverValue, value });
  };
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleChange = (v: number) => {
    setLocalValue(v);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(
      () => updateSetting(setting.key, v),
      DEBOUNCE_MS,
    );
  };

  const formatValue = (v: number) => {
    if (setting.unit === "ms") return `${(v / 1000).toFixed(1)}s`;
    return v.toFixed(2);
  };

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-base text-foreground">{setting.label}</span>
        <span className="text-xs text-muted-foreground/70 tabular-nums">
          {formatValue(localValue)}
        </span>
      </div>
      <Slider
        min={setting.min ?? 0}
        max={setting.max ?? 1}
        step={setting.step ?? 0.01}
        value={[localValue]}
        onValueChange={([v]) => {
          if (v !== undefined) handleChange(v);
        }}
      />
      {setting.description && (
        <p className="text-sm text-muted-foreground">{setting.description}</p>
      )}
    </div>
  );
}

// A free text value, such as the address of a speech model on the agent's own machine. It
// saves when the user leaves the field or presses Enter, and empty text saves nothing.
function TextSetting({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const serverValue =
    typeof setting.value === "string"
      ? setting.value
      : typeof setting.default === "string"
        ? setting.default
        : "";
  // The pending edit, keyed by the server value it was made against, so a server change
  // shows through.
  const [edit, setEdit] = useState<{ base: string; value: string } | null>(
    null,
  );
  const value =
    edit !== null && edit.base === serverValue ? edit.value : serverValue;
  const save = () => {
    const next = value.trim();
    if (next && next !== serverValue) updateSetting(setting.key, next);
  };
  return (
    <Field orientation="vertical" className="gap-1.5">
      <FieldLabel className="text-base" htmlFor={`voice-${setting.key}`}>
        {setting.label}
      </FieldLabel>
      <Input
        id={`voice-${setting.key}`}
        value={value}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => {
          setEdit({ base: serverValue, value: e.target.value });
        }}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
        }}
      />
      {setting.description && (
        <FieldDescription>{setting.description}</FieldDescription>
      )}
    </Field>
  );
}

function SelectSetting({
  setting,
  updateSetting,
}: {
  setting: SettingDef;
  updateSetting: (key: string, value: unknown) => void;
}) {
  const options = setting.options ?? [];
  const hasPreview = options.some((o) => o.preview);
  const onChange = (v: string) => updateSetting(setting.key, v);

  if (hasPreview) return <VoicePicker setting={setting} onChange={onChange} />;

  return (
    <OptionList
      label={setting.label}
      selected={typeof setting.value === "string" ? setting.value : null}
      options={options}
      onChange={onChange}
    />
  );
}

// One choice from a short list, closed until the user opens it: a select setting, and the
// provider of a role.
export function OptionList({
  label,
  selected,
  options,
  onChange,
}: {
  label: string;
  selected: string | null;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <Collapsible>
      <CollapsibleChevronButton>
        {label}:{" "}
        <span className="text-foreground font-medium">
          {options.find((o) => o.value === selected)?.label ?? "Unknown"}
        </span>
      </CollapsibleChevronButton>
      <CollapsibleContent>
        <div className="flex flex-col gap-1 pt-2 px-6">
          {options.map((opt) => (
            <button
              key={opt.value}
              aria-pressed={opt.value === selected}
              className={`text-left text-base px-2 py-1 rounded ${opt.value === selected ? "bg-primary/10 text-primary" : "hover:bg-muted text-foreground"}`}
              onClick={() => onChange(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

const DEBOUNCE_MS = 400;

// --- Shared usage collapsible ---
