import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { Orb } from "@/components/Orb";

const MIN_DISPLAY_MS = 1000;

interface LoadingScreenProps {
  ready: boolean;
  onFinished: () => void;
}

export function LoadingScreen({ ready, onFinished }: LoadingScreenProps) {
  const [minElapsed, setMinElapsed] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setMinElapsed(true), MIN_DISPLAY_MS);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (ready && minElapsed) {
      onFinished();
    }
  }, [ready, minElapsed, onFinished]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="absolute inset-0 z-50 flex items-center justify-center"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
      >
        <Orb state="loading" size={96} />
      </motion.div>
    </motion.div>
  );
}
