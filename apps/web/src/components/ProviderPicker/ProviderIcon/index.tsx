import { useState } from "react";

const ICON_BASE = "https://openrouter.ai/images/icons";

export function ProviderIcon({
  name,
  className = "size-8",
}: {
  name: string;
  className?: string;
}) {
  const [src, setSrc] = useState(`${ICON_BASE}/${name}.svg`);
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div
        className={`${className} shrink-0 flex items-center justify-center rounded-md bg-muted text-xs font-semibold text-muted-foreground`}
      >
        {name.charAt(0).toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt=""
      className={`${className} shrink-0 rounded-md bg-white/5 object-contain p-0.5`}
      onError={() => {
        if (src.endsWith(".svg")) {
          setSrc(`${ICON_BASE}/${name}.png`);
        } else {
          setFailed(true);
        }
      }}
    />
  );
}
