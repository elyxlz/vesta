import { useEffect, useState } from "react";

interface ProgressBarProps {
  message?: string;
}

export function ProgressBar({ message }: ProgressBarProps) {
  const [displayMessage, setDisplayMessage] = useState(message);

  useEffect(() => {
    setDisplayMessage(message);
  }, [message]);

  return (
    <div className="flex flex-col items-center gap-2 w-full">
      <div className="w-full max-w-[200px] h-[3px] bg-black/5 rounded-full overflow-hidden">
        <div className="h-full w-1/3 bg-foreground/30 rounded-full animate-progress" />
      </div>
      {displayMessage && (
        <p className="text-[11px] text-muted animate-fade-slide-in" key={displayMessage}>
          {displayMessage}
        </p>
      )}
    </div>
  );
}
