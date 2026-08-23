// The voice service's status wire shapes, shared by every client's voice UI and
// session logic. The agent-side voice daemon produces them (GET /agents/{name}/voice/
// {stt|tts}/status); settings are provider-declared and rendered generically.

export interface VoiceSettingOption {
  value: string
  label: string
  description?: string
  preview?: string
  custom?: boolean
}

export interface VoiceSettingDef {
  key: string
  type: "bool" | "number" | "select"
  label: string
  description?: string
  value: unknown
  default?: unknown
  min?: number
  max?: number
  step?: number
  unit?: string
  config?: VoiceSettingDef[]
  config_label?: string
  options?: VoiceSettingOption[]
}

export interface VoiceDomainStatus {
  configured: boolean
  provider: string | null
  enabled?: boolean
  settings?: VoiceSettingDef[]
}

export function voiceDomainReady(status: VoiceDomainStatus | null): boolean {
  return status !== null && status.configured && status.enabled === true
}

export function voiceBoolSetting(
  status: VoiceDomainStatus | null,
  key: string,
  fallback: boolean,
): boolean {
  const value = status?.settings?.find((setting) => setting.key === key)?.value
  return typeof value === "boolean" ? value : fallback
}
