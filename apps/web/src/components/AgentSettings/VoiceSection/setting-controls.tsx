import { useEffect, useRef, useState } from "react";
import { Play, Square, ChevronDown } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { setVoiceSetting, type SettingDef } from "@/lib/voice";
import { useOptimisticToggle } from "./use-optimistic-toggle";
import { Button } from "@/components/ui/button";

export function DynamicSettings({
  settings,
  domain,
  agentName,
  onSettingChange,
}: {
  settings: SettingDef[];
  domain: "stt" | "tts";
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
    <Collapsible>
      <CollapsibleChevronButton>
        {setting.label}:{" "}
        <span className="text-foreground font-medium">
          {options.find((o) => o.value === setting.value)?.label ?? "Unknown"}
        </span>
      </CollapsibleChevronButton>
      <CollapsibleContent>
        <div className="flex flex-col gap-1 pt-2 px-6">
          {options.map((opt) => (
            <button
              key={opt.value}
              className={`text-left text-base px-2 py-1 rounded ${opt.value === setting.value ? "bg-primary/10 text-primary" : "hover:bg-muted text-foreground"}`}
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

// --- Voice picker (rich select with previews) ---

function VoicePicker({
  setting,
  onChange,
}: {
  setting: SettingDef;
  onChange: (v: string) => void;
}) {
  const options = setting.options ?? [];
  const [playingId, setPlayingId] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current = null;
      }
    };
  }, []);

  const selectedId = typeof setting.value === "string" ? setting.value : null;
  const selectedOption = options.find((o) => o.value === selectedId);

  const select = (opt: { value: string }) => {
    onChange(opt.value);
  };

  const playPreview = (opt: { value: string; preview?: string }) => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (playingId === opt.value) {
      setPlayingId(null);
      return;
    }
    if (!opt.preview) return;
    const audio = new Audio(opt.preview);
    audio.onended = () => setPlayingId(null);
    audio.play().catch(() => {
      if (audioRef.current === audio) audioRef.current = null;
      setPlayingId((current) => (current === opt.value ? null : current));
    });
    audioRef.current = audio;
    setPlayingId(opt.value);
  };

  return (
    <Collapsible>
      <CollapsibleChevronButton>
        {setting.label}:{" "}
        <span className="text-foreground font-medium">
          {selectedOption?.label ?? "Unknown"}
        </span>
      </CollapsibleChevronButton>

      <CollapsibleContent>
        <div className="grid grid-cols-4 sm:grid-cols-5 gap-2 pt-2">
          {options.map((opt) => {
            const selected = opt.value === selectedId;
            const playing = playingId === opt.value;
            return (
              <div key={opt.value} className="group relative">
                <button
                  className={`flex flex-col items-center gap-1.5 rounded-lg p-2 transition-colors cursor-pointer w-full ${
                    selected
                      ? "bg-primary/10 ring-1 ring-ring"
                      : "hover:bg-muted"
                  }`}
                  onClick={() => select(opt)}
                  aria-pressed={selected}
                >
                  <div
                    className={`size-9 rounded-full flex items-center justify-center text-sm font-medium ${
                      selected
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground"
                    }`}
                  >
                    {opt.label[0]}
                  </div>
                  <span
                    className={`text-xs leading-tight text-center truncate max-w-full ${
                      selected
                        ? "text-primary font-medium"
                        : "text-muted-foreground"
                    }`}
                  >
                    {opt.label}
                  </span>
                  {typeof opt.description === "string" && opt.description && (
                    <span className="text-xs leading-tight text-center text-muted-foreground truncate max-w-full">
                      {opt.description}
                    </span>
                  )}
                </button>
                {opt.preview && (
                  <button
                    aria-label={playing ? "Stop preview" : "Play preview"}
                    className="absolute top-2 left-1/2 -translate-x-1/2 size-9 rounded-full bg-black/40 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 flex items-center justify-center cursor-pointer transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      playPreview(opt);
                    }}
                  >
                    {playing ? (
                      <Square className="size-3 text-white" />
                    ) : (
                      <Play className="size-3 text-white ml-0.5" />
                    )}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

const DEBOUNCE_MS = 400;

export function CollapsibleChevronButton({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <CollapsibleTrigger asChild>
      <Button
        variant="ghost"
        size="sm"
        className="w-full justify-start gap-2 px-0 text-base text-muted-foreground hover:text-foreground"
      >
        <ChevronDown className="size-4 transition-transform [[data-state=closed]_&]:-rotate-90" />
        {children}
      </Button>
    </CollapsibleTrigger>
  );
}

// --- Shared usage collapsible ---
