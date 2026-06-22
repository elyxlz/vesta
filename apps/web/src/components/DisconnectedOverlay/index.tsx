import { motion } from "motion/react";
import { LogOut } from "lucide-react";
import { useAuth } from "@/providers/AuthProvider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

export function DisconnectedOverlay() {
  const { disconnect } = useAuth();

  return (
    <motion.div
      role="alertdialog"
      aria-modal="true"
      aria-label="disconnected from gateway"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-muted/80 backdrop-blur-sm"
    >
      <Empty className="border-none">
        <EmptyHeader>
          <Spinner className="size-6" />
          <EmptyTitle>disconnected from gateway</EmptyTitle>
          <EmptyDescription>attempting to reconnect…</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button variant="destructive" onClick={() => disconnect()}>
            <LogOut data-icon="inline-start" />
            Disconnect
          </Button>
        </EmptyContent>
      </Empty>
    </motion.div>
  );
}
