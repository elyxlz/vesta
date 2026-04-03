import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldGroup, FieldLabel, FieldDescription } from "@/components/ui/field";
import { ProgressBar } from "@/components/ProgressBar";
import { AuthFlow } from "@/components/AuthFlow";
import {
  createAgent,
  deleteAgent,
  startAgent,
  waitForReady,
  restoreAgent,
  checkPlatform,
  setupPlatform,
  authenticate,
  type AuthStartResult,
} from "@/api";
import { isTauri } from "@/lib/env";
import { fadeSlide } from "@/lib/motion";
import { detectPlatform } from "@/lib/platform";
import { openExternalUrl } from "@/lib/open-external-url";
import { useAgents } from "@/providers/AgentsProvider";
import { useNavigate } from "react-router-dom";
import { friendlyError } from "./errors";

type Step = "platform" | "name" | "creating" | "auth" | "done";

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

export function CreateAgent() {
  const navigate = useNavigate();
  const { agents, refreshAgents } = useAgents();

  const hasAgents = agents.length > 0;

  const [step, setStep] = useState<Step>("name");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [errorDetails, setErrorDetails] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [creatingMsg, setCreatingMsg] = useState(0);
  const [createdName, setCreatedName] = useState("");
  const [authStart, setAuthStart] = useState<AuthStartResult | null>(null);

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

  const handleCreate = async () => {
    const normalized = normalizeName(name);
    if (!normalized) return;

    setError("");
    setErrorDetails("");
    setAuthStart(null);
    setCreatedName(normalized);
    setStep("creating");
    setCreatingMsg(0);

    let created = false;

    try {
      await createAgent(normalized);
      created = true;
      await refreshAgents();
      await startAgent(normalized);
      await refreshAgents();
      await waitForReady(normalized, 180);
      await refreshAgents();
      const nextAuthStart = await authenticate(normalized);
      setAuthStart(nextAuthStart);
      setStep("auth");
      void openExternalUrl(nextAuthStart.auth_url);
    } catch (e: unknown) {
      if (created) {
        await refreshAgents();
      }
      const raw = (e as { message?: string })?.message || "creation failed";
      const friendly = friendlyError(raw);
      setError(friendly);
      if (friendly !== raw) setErrorDetails(raw);
      setStep("name");
    }
  };

  const handleRestore = () => {
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
        navigate("/");
      } catch (e: unknown) {
        setError((e as { message?: string })?.message || "restore failed");
        setStep("name");
      }
    };
    input.click();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape" && hasAgents) navigate("/");
  };

  const content = (() => {
    if (step === "platform") {
      return (
        <PlatformSetup
          onReady={() => setStep("name")}
          onCancel={hasAgents ? () => navigate("/") : undefined}
        />
      );
    }

    if (step === "creating") {
      return (
        <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
          <h2 className="text-base font-semibold">setting up</h2>
          <p className="text-xs text-muted-foreground">
            this may take a couple of mins.
          </p>
          <ProgressBar message={CREATING_MESSAGES[creatingMsg]} />
        </div>
      );
    }

    if (step === "auth") {
      return (
        <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
          {authStart ? (
            <AuthFlow
              agentName={createdName}
              authUrl={authStart.auth_url}
              sessionId={authStart.session_id}
              onCancel={async () => {
                setAuthStart(null);
                try {
                  await deleteAgent(createdName);
                } catch {}
                await refreshAgents();
                navigate("/");
              }}
              onComplete={() => {
                setAuthStart(null);
                setStep("done");
              }}
            />
          ) : null}
        </div>
      );
    }

    if (step === "done") {
      return (
        <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
          <div className="size-10 rounded-full bg-primary/20 flex items-center justify-center">
            <Check size={20} className="text-primary" />
          </div>
          <h2 className="text-base font-semibold">
            {createdName} is ready
          </h2>
          <p className="text-xs text-muted-foreground">say hi.</p>
          <Button
            className="w-full"
            onClick={() => navigate(`/agent/${createdName}`, { state: { panel: "chat" } })}
          >
            continue
          </Button>
        </div>
      );
    }

    return (
      <div className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4">
        <div className="flex flex-col items-center gap-1 text-center">
          <h2 className="text-base font-semibold">new agent</h2>
          <FieldDescription>
            give it a name to get started.
          </FieldDescription>
        </div>

        <FieldGroup className="gap-3">
          <Field>
            <FieldLabel htmlFor="agent-name" className="sr-only">Name</FieldLabel>
            <Input
              id="agent-name"
              placeholder="name your agent"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
              className="text-center text-sm"
            />
          </Field>
        </FieldGroup>

        <Button
          onClick={handleCreate}
          disabled={!normalizeName(name)}
          className="w-full"
        >
          create
        </Button>

        <Button
          variant="link"
          onClick={handleRestore}
          className="h-auto px-0 py-0 text-xs font-normal text-muted-foreground underline underline-offset-4 hover:bg-transparent hover:text-foreground"
        >
          restore from backup
        </Button>

        {error && (
          <div className="text-center">
            <p className="text-xs text-destructive">{error}</p>
            {errorDetails && (
              <>
                <Button
                  variant="link"
                  size="sm"
                  onClick={() => setShowDetails(!showDetails)}
                >
                  {showDetails ? "hide details" : "show details"}
                </Button>
                {showDetails && (
                  <p className="text-xs text-muted-foreground break-all">
                    {errorDetails}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    );
  })();

  return (
    <div className="flex flex-col h-full ">
      <div className="flex-1 flex items-center justify-center">
        <AnimatePresence mode="wait">
          <motion.div key={step} {...fadeSlide}>
            {content}
          </motion.div>
        </AnimatePresence>
      </div>
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

  const doCheck = async () => {
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
  };

  useEffect(() => {
    doCheck();
  }, [doCheck]);

  const handleInstall = async () => {
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
  };

  if (checking) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
        <h2 className="text-base font-semibold">checking system</h2>
        <p className="text-xs text-muted-foreground">
          making sure everything is ready...
        </p>
        <ProgressBar />
      </div>
    );
  }

  if (status?.needs_reboot) {
    return (
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
        <h2 className="text-base font-semibold">restart required</h2>
        <p className="text-xs text-muted-foreground text-center">
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
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
        <h2 className="text-base font-semibold">enable virtualization</h2>
        <div className="text-xs text-muted-foreground text-left flex flex-col gap-1">
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
      <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
        <h2 className="text-base font-semibold">setting up windows</h2>
        <p className="text-xs text-muted-foreground text-center">
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
            <p className="text-xs text-destructive">{error}</p>
            <Button
              variant="link"
              size="sm"
              onClick={() => setShowDetails(!showDetails)}
            >
              {showDetails ? "hide details" : "show details"}
            </Button>
            {showDetails && (
              <p className="text-xs text-muted-foreground break-all">{error}</p>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4 ">
      <h2 className="text-base font-semibold">setting up</h2>
      {busy ? (
        <ProgressBar />
      ) : (
        <>
          {error && (
            <p className="text-xs text-destructive ">
              {error}
            </p>
          )}
          <Button size="sm" onClick={handleInstall}>
            retry
          </Button>
        </>
      )}
      {onCancel && (
        <Button
          variant="link"
          size="sm"
          onClick={onCancel}
        >
          cancel
        </Button>
      )}
    </div>
  );
}
