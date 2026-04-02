import { useCallback, useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProgressBar } from "@/components/ProgressBar";
import { AuthFlow } from "@/components/AuthFlow";
import {
  createAgent,
  waitForReady,
  restoreAgent,
  checkPlatform,
  setupPlatform,
} from "@/api";
import { isTauri } from "@/lib/env";
import { detectPlatform } from "@/lib/platform";
import { useNavigation } from "@/stores/use-navigation";
import { friendlyError } from "./errors";

type Step = "platform" | "name" | "creating" | "auth" | "done";

interface CreateAgentProps {
  onCancel?: () => void;
  onCreated?: () => void;
}

const CREATING_MESSAGES = [
  "setting things up...",
  "preparing email & calendar access...",
  "loading browser & research tools...",
  "setting up reminders & tasks...",
  "almost there...",
];

function normalizeName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

export function CreateAgent({ onCancel, onCreated }: CreateAgentProps) {
  const navigateToChat = useNavigation((s) => s.navigateToChat);

  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [creatingMsg, setCreatingMsg] = useState(0);
  const [createdName, setCreatedName] = useState("");

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isTauri && detectPlatform() === "windows") {
      setStep("platform");
    }
  }, []);

  useEffect(() => {
    if (step !== "creating") return;
    let idx = 0;
    timerRef.current = setInterval(() => {
      idx = Math.min(idx + 1, CREATING_MESSAGES.length - 1);
      setCreatingMsg(idx);
    }, 3000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [step]);

  const handleCreate = useCallback(async () => {
    const normalized = normalizeName(name);
    if (!normalized) return;

    setError("");
    setErrorDetails("");
    setCreatedName(normalized);
    setStep("creating");
    setCreatingMsg(0);

    try {
      await createAgent(normalized);
      await waitForReady(normalized, 180);
      setStep("auth");
    } catch (e: unknown) {
      const raw = (e as { message?: string })?.message || "creation failed";
      const friendly = friendlyError(raw);
      setError(friendly);
      if (friendly !== raw) setErrorDetails(raw);
      setStep("name");
    }
  }, [name]);

  const handleRestore = useCallback(() => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".tar.gz,.gz";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      setStep("creating");
      setCreatingMsg(0);
      setError("");
      try {
        await restoreAgent(file);
        onCreated?.();
      } catch (e: unknown) {
        setError((e as { message?: string })?.message || "restore failed");
        setStep("name");
      }
    };
    input.click();
  }, [onCreated]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleCreate();
      if (e.key === "Escape" && onCancel) onCancel();
    },
    [handleCreate, onCancel],
  );

  if (step === "platform") {
    return (
      <PlatformSetup
        onReady={() => setStep("name")}
        onCancel={onCancel}
      />
    );
  }

  if (step === "creating") {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <h2 className="text-[15px] font-semibold">setting up</h2>
        <p className="text-[11px] text-muted">
          this may take a couple of mins.
        </p>
        <ProgressBar message={CREATING_MESSAGES[creatingMsg]} />
        {onCancel && (
          <button
            onClick={() => {
              setStep("name");
              onCancel?.();
            }}
            className="text-[11px] text-muted hover:text-foreground mt-2"
          >
            cancel
          </button>
        )}
      </div>
    );
  }

  if (step === "auth") {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <AuthFlow
          agentName={createdName}
          onCancel={() => setStep("name")}
          onComplete={() => setStep("done")}
        />
      </div>
    );
  }

  if (step === "done") {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <div className="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center animate-pop-in">
          <Check size={20} className="text-green-600" />
        </div>
        <h2 className="text-[15px] font-semibold">
          {createdName} is ready
        </h2>
        <p className="text-[11px] text-muted">say hi.</p>
        <Button
          size="sm"
          className="w-full"
          onClick={() => {
            onCreated?.();
            navigateToChat(createdName);
          }}
        >
          continue
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
      <div className="text-center">
        <h2 className="text-[15px] font-semibold">new agent</h2>
        <p className="text-[11px] text-muted mt-1">
          give it a name to get started.
        </p>
      </div>

      <Input
        placeholder="name your agent"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={handleKeyDown}
        autoFocus
        className="text-center text-[13px]"
      />

      <Button
        onClick={handleCreate}
        disabled={!normalizeName(name)}
        size="sm"
        className="w-full"
      >
        create
      </Button>

      <button
        onClick={handleRestore}
        className="text-[11px] text-muted hover:text-foreground"
      >
        restore from backup
      </button>

      {onCancel && (
        <button
          onClick={onCancel}
          className="text-[11px] text-muted hover:text-foreground"
        >
          cancel
        </button>
      )}

      {error && (
        <div className="text-center animate-shake">
          <p className="text-[11px] text-destructive">{error}</p>
          {errorDetails && (
            <>
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-[10px] text-muted hover:text-foreground mt-1"
              >
                {showDetails ? "hide details" : "show details"}
              </button>
              {showDetails && (
                <p className="text-[10px] text-muted mt-1 break-all">
                  {errorDetails}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function PlatformSetup({
  onReady,
  onCancel,
}: {
  onReady: () => void;
  onCancel?: () => void;
}) {
  const [checking, setChecking] = useState(true);
  const [status, setStatus] = useState<{
    needs_reboot: boolean;
    wsl_installed: boolean;
    virtualization_enabled: boolean | null;
    ready: boolean;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  const doCheck = useCallback(async () => {
    setChecking(true);
    try {
      const s = await checkPlatform();
      setStatus(s);
      if (s.ready) {
        onReady();
        return;
      }
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "check failed");
    } finally {
      setChecking(false);
    }
  }, [onReady]);

  useEffect(() => {
    doCheck();
  }, [doCheck]);

  const handleInstall = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const result = await setupPlatform();
      if (result.ready) {
        onReady();
      } else {
        setStatus(result);
      }
    } catch (e: unknown) {
      setError((e as { message?: string })?.message || "setup failed");
    } finally {
      setBusy(false);
    }
  }, [onReady]);

  if (checking) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <h2 className="text-[15px] font-semibold">checking system</h2>
        <p className="text-[11px] text-muted">
          making sure everything is ready...
        </p>
        <ProgressBar />
      </div>
    );
  }

  if (status?.needs_reboot) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <h2 className="text-[15px] font-semibold">restart required</h2>
        <p className="text-[11px] text-muted text-center">
          restart your computer to finish setup, then reopen vesta.
        </p>
        <Button size="sm" onClick={doCheck}>
          check again
        </Button>
      </div>
    );
  }

  if (status?.virtualization_enabled === false) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <h2 className="text-[15px] font-semibold">enable virtualization</h2>
        <div className="text-[11px] text-muted text-left space-y-1">
          <p>1. Restart your computer</p>
          <p>2. Enter BIOS/UEFI settings</p>
          <p>3. Enable Intel VT-x or AMD-V</p>
          <p>4. Save and restart</p>
        </div>
        <Button size="sm" onClick={doCheck}>
          check again
        </Button>
      </div>
    );
  }

  if (!status?.wsl_installed) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
        <h2 className="text-[15px] font-semibold">setting up windows</h2>
        <p className="text-[11px] text-muted text-center">
          WSL2 needs to be installed to run vesta agents.
        </p>
        {busy ? (
          <ProgressBar />
        ) : (
          <Button size="sm" onClick={handleInstall}>
            install WSL2
          </Button>
        )}
        {error && (
          <div className="text-center">
            <p className="text-[11px] text-destructive">{error}</p>
            <button
              onClick={() => setShowDetails(!showDetails)}
              className="text-[10px] text-muted hover:text-foreground mt-1"
            >
              {showDetails ? "hide details" : "show details"}
            </button>
            {showDetails && (
              <p className="text-[10px] text-muted mt-1 break-all">{error}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 animate-fade-slide-in">
      <h2 className="text-[15px] font-semibold">setting up</h2>
      {busy ? (
        <ProgressBar />
      ) : (
        <>
          {error && (
            <p className="text-[11px] text-destructive animate-shake">
              {error}
            </p>
          )}
          <Button size="sm" onClick={handleInstall}>
            retry
          </Button>
        </>
      )}
      {onCancel && (
        <button
          onClick={onCancel}
          className="text-[11px] text-muted hover:text-foreground"
        >
          cancel
        </button>
      )}
    </div>
  );
}
