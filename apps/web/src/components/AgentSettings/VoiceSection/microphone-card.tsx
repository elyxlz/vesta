import { useEffect } from "react";
import { Mic } from "lucide-react";
import { useResource } from "@vesta/core/react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldDescription } from "@/components/ui/field";
import { runtimeInfo } from "@/lib/native";
import {
  allowMicrophone,
  listMicrophones,
  microphoneDeniedMessage,
} from "@/lib/voice";
import { usePreferences } from "@/stores/use-preferences";
import { useToast } from "@/stores/use-toast";
import { OptionList } from "./setting-controls";

// The option for no stored device; a device id is never empty.
const SYSTEM_DEFAULT = "";

// The microphone both mic modes record from, on this device only. A session that is open keeps
// its microphone; the next one uses the new choice.
export function MicrophoneCard() {
  const voiceInput = usePreferences((s) => s.voiceInput);
  const update = usePreferences((s) => s.update);
  const devices = useResource("microphones", listMicrophones);
  const { reload } = devices;
  const toast = useToast();

  useEffect(() => {
    if (!("mediaDevices" in navigator)) return;
    const media = navigator.mediaDevices;
    media.addEventListener("devicechange", reload);
    return () => {
      media.removeEventListener("devicechange", reload);
    };
  }, [reload]);

  const microphones = devices.data?.microphones ?? [];
  // A stored device that is not plugged in reads as the default, which is what a session uses.
  const selected = microphones.some((m) => m.id === voiceInput)
    ? voiceInput
    : SYSTEM_DEFAULT;

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          <Mic className="size-4 text-muted-foreground" />
          microphone
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <OptionList
          label="input"
          selected={selected}
          options={[
            { value: SYSTEM_DEFAULT, label: "system default" },
            ...microphones.map((m) => ({ value: m.id, label: m.label })),
          ]}
          onChange={(value) => {
            update({ voiceInput: value === SYSTEM_DEFAULT ? null : value });
          }}
        />
        {devices.data !== null && !devices.data.named && (
          <div className="flex items-center justify-between gap-3">
            <FieldDescription>
              allow the microphone to see the name of each one
            </FieldDescription>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                allowMicrophone().then(reload, () => {
                  toast.error(microphoneDeniedMessage(runtimeInfo));
                });
              }}
            >
              allow
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
