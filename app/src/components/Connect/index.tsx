import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FieldGroup, Field, FieldLabel, FieldDescription } from "@/components/ui/field";
import { fadeSlide } from "@/lib/motion";
import { useAuth } from "@/providers/AuthProvider";

export function Connect() {
  const { connect } = useAuth();
  const navigate = useNavigate();

  const [host, setHost] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [details, setDetails] = useState("");
  const [showDetails, setShowDetails] = useState(false);
  const [busy, setBusy] = useState(false);

  const handleConnect = async () => {
    if (!host.trim() || !apiKey.trim() || busy) return;
    setBusy(true);
    setError("");
    setDetails("");

    try {
      const url = host.includes("://") ? host.trim() : `https://${host.trim()}`;
      await connect(url, apiKey.trim());
      navigate("/", { replace: true });
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message || "connection failed";
      if (msg === "could not reach server") {
        setError("could not reach server");
      } else {
        setError("could not reach server");
        setDetails(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    handleConnect();
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 flex items-center justify-center">
        <form
          onSubmit={handleSubmit}
          className="flex flex-col items-center gap-3 w-[240px] max-w-full px-4"
        >
          <div className="flex flex-col items-center gap-1 text-center">
            <h2 className="text-base font-semibold">connect</h2>
            <FieldDescription>
              connect to a remote vesta server.
            </FieldDescription>
          </div>

          <FieldGroup className="gap-3">
            <Field>
              <FieldLabel htmlFor="url" className="sr-only">Host</FieldLabel>
              <Input
                id="url"
                name="url"
                placeholder="host"
                autoComplete="url"
                value={host}
                onChange={(e) => setHost(e.target.value)}
                className="text-center text-sm"
              />
            </Field>

            <Field>
              <FieldLabel htmlFor="key" className="sr-only">Key</FieldLabel>
              <Input
                id="key"
                name="password"
                type="password"
                placeholder="key"
                autoComplete="current-password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="text-center text-sm"
              />
            </Field>
          </FieldGroup>

          <Button
            type="submit"
            disabled={!host.trim() || !apiKey.trim() || busy}
            className="w-full"
          >
            {busy ? "connecting..." : "connect"}
          </Button>

          <AnimatePresence>
            {error && (
              <motion.div {...fadeSlide} className="flex flex-col items-center gap-1 text-center">
                <p
                  className={`text-xs ${details ? "cursor-pointer" : ""}`}
                  onClick={details ? () => setShowDetails(!showDetails) : undefined}
                >
                  <span className="text-destructive">{error}</span>{details && (
                    <span className="text-foreground"> · {showDetails ? "hide details" : "show details"}</span>
                  )}
                </p>
                {showDetails && details && (
                  <p className="text-xs text-muted-foreground break-all">
                    {details}
                  </p>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </form>
      </div>
    </div>
  );
}
