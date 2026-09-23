import { createContext, use, useState, type ReactNode } from "react";
import type { ProviderKind } from "@vesta/core";

// A setup in progress, carried across its stack screens. Credentials stay in memory, never in a
// route param, and the draft ends when the settings sheet closes.
export interface ProviderDraft {
  kind: ProviderKind | null;
  credentials: string | null;
  key: string;
  model: string;
}

const EMPTY_DRAFT: ProviderDraft = {
  kind: null,
  credentials: null,
  key: "",
  model: "",
};

interface ProviderDraftValue {
  draft: ProviderDraft;
  start: (kind: ProviderKind) => void;
  update: (patch: Partial<ProviderDraft>) => void;
}

const ProviderDraftContext = createContext<ProviderDraftValue | null>(null);

export function ProviderDraftProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<ProviderDraft>(EMPTY_DRAFT);
  const value: ProviderDraftValue = {
    draft,
    start: (kind) => setDraft({ ...EMPTY_DRAFT, kind }),
    update: (patch) => setDraft((current) => ({ ...current, ...patch })),
  };
  return <ProviderDraftContext value={value}>{children}</ProviderDraftContext>;
}

export function useProviderDraft(): ProviderDraftValue {
  const value = use(ProviderDraftContext);
  if (!value)
    throw new Error(
      "useProviderDraft must be used inside ProviderDraftProvider",
    );
  return value;
}
