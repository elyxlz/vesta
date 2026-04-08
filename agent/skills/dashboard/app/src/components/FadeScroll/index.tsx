import { useCallback, useRef, useState, type ReactNode } from "react";

interface FadeScrollProps {
  className?: string;
  children: ReactNode;
}

export function FadeScroll({ className, children }: FadeScrollProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [fadeTop, setFadeTop] = useState(false);
  const [fadeBottom, setFadeBottom] = useState(false);

  const updateFades = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    setFadeTop(el.scrollTop > 2);
    setFadeBottom(el.scrollHeight - el.scrollTop - el.clientHeight > 2);
  }, []);

  return (
    <div
      ref={scrollRef}
      onScroll={updateFades}
      className={className ?? "w-full h-full overflow-y-auto"}
      style={{
        maskImage: `linear-gradient(to bottom, ${fadeTop ? "transparent" : "black"}, black 24px, black calc(100% - 24px), ${fadeBottom ? "transparent" : "black"})`,
      }}
    >
      {children}
    </div>
  );
}
