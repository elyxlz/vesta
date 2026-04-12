import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field";
import { ProgressBar } from "@/components/ProgressBar";
import { AuthFlow } from "@/components/AuthFlow";
import {
  createAgent,
  deleteAgent,
  authenticate,
  waitForReady,
  type AuthStartResult,
} from "@/api";
import { fadeSlide } from "@/lib/motion";
import { useTauri } from "@/providers/TauriProvider";
import { useGateway } from "@/providers/GatewayProvider";
import { useNavigate } from "react-router-dom";
import { friendlyError } from "./errors";

type Step = "platform" | "name" | "creating" | "auth" | "finalizing" | "done";

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

export function NewAgent() {
  const { isTauri, isWindows } = useTauri();
  const navigate = useNavigate();
  const { agents } = useGateway();

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
    if (isTauri && isWindows) {
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
      const nextAuthStart = await authenticate(normalized);
      setAuthStart(nextAuthStart);
      setStep("auth");
    } catch (e: unknown) {
      const raw = (e as { message?: string })?.message || "creation failed";
      const friendly = friendlyError(raw);
      setError(friendly);
      if (friendly !== raw) setErrorDetails(raw);
      setStep("name");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape" && hasAgents) navigate("/home");
  };

  const content = (() => {
    if (step === "creating") {
      return (
        <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
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
        <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
          {authStart ? (
            <AuthFlow
              agentName={createdName}
              authUrl={authStart.auth_url}
              sessionId={authStart.session_id}
              onCancel={async () => {
                const agentToRemove = createdName;
                const hasOtherAgents = agents.length > 1;
                setAuthStart(null);

                if (hasOtherAgents) {
                  navigate("/home");
                } else {
                  setStep("name");
                }

                try {
                  await deleteAgent(agentToRemove);
                } catch {}
              }}
              onComplete={async () => {
                setAuthStart(null);
                setStep("finalizing");
                // Poll wait-ready in short bursts to avoid tunnel timeouts
                for (let i = 0; i < 18; i++) {
                  try {
                    await waitForReady(createdName, 10);
                    break;
                  } catch {
                    if (i === 17) break;
                  }
                }
                setStep("done");
              }}
            />
          ) : null}
        </div>
      );
    }

    if (step === "finalizing") {
      return (
        <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
          <h2 className="text-base font-semibold">setting up</h2>
          <ProgressBar message="this may take a couple of mins" />
        </div>
      );
    }

    if (step === "done") {
      return (
        <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
          <div className="size-10 rounded-full bg-primary/20 flex items-center justify-center">
            <Check size={20} className="text-primary" />
          </div>
          <h2 className="text-base font-semibold">{createdName} is ready</h2>
          <p className="text-xs text-muted-foreground">say hi.</p>
          <Button
            className="w-full"
            onClick={() =>
              navigate(`/agent/${createdName}`, { state: { panel: "chat" } })
            }
          >
            continue
          </Button>
        </div>
      );
    }

    return (
      <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
        <div className="flex flex-col items-center gap-1 text-center">
          <h2 className="text-base font-semibold">new agent</h2>
          <FieldDescription>give it a name to get started.</FieldDescription>
        </div>

        <FieldGroup className="gap-3">
          <Field>
            <FieldLabel htmlFor="agent-name" className="sr-only">
              Name
            </FieldLabel>
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
