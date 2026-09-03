import {
  useCallback,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from "react";

export interface Resource<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
  // Replace the loaded value for the current key after a write, so an edit lands without a refetch.
  set: (data: T) => void;
}

export interface ResourceOptions {
  // Reload after a failure, forever while mounted; unset means one attempt per key.
  retryMs?: number;
}

interface Settled<T> {
  key: string;
  nonce: number;
  data: T | null;
  error: unknown;
}

// One remote value per key: load it when the key changes, drop a result that lands for a previous
// key, and never write state synchronously in the effect. `loading` is derived from the settled
// entry's key and reload nonce, so a key change is loading again without a reset, and a reload
// keeps the last data showing until the new answer arrives. `load` is an effect event, so an inline
// closure over the latest props is the normal way to call it and never restarts the load; it
// receives the key it loads for.
export function useResource<T>(
  key: string | null,
  load: (key: string) => Promise<T>,
  options: ResourceOptions = {},
): Resource<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [nonce, setNonce] = useState(0);
  const run = useEffectEvent(load);
  const { retryMs } = options;

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    run(key).then(
      (data) => {
        if (!cancelled) setSettled({ key, nonce, data, error: null });
      },
      (error: unknown) => {
        if (cancelled) return;
        setSettled((previous) => ({
          key,
          nonce,
          data:
            previous !== null && previous.key === key ? previous.data : null,
          error,
        }));
        if (retryMs !== undefined) {
          retry = setTimeout(() => {
            setNonce((current) => current + 1);
          }, retryMs);
        }
      },
    );
    return () => {
      cancelled = true;
      if (retry !== null) clearTimeout(retry);
    };
  }, [key, nonce, retryMs]);

  // `set` and `reload` keep one identity for the hook's life, so a caller can list them as
  // effect or callback deps; `set` reads the key it applies to at call time.
  const latest = useRef({ key, nonce });
  useEffect(() => {
    latest.current = { key, nonce };
  });
  const reload = useCallback(() => {
    setNonce((value) => value + 1);
  }, []);
  const set = useCallback((data: T) => {
    const target = latest.current;
    if (target.key !== null)
      setSettled({ key: target.key, nonce: target.nonce, data, error: null });
  }, []);

  const current = settled !== null && settled.key === key ? settled : null;
  const fresh = current !== null && current.nonce === nonce;
  return {
    data: current?.data ?? null,
    error: fresh ? current.error : null,
    loading: key !== null && !fresh,
    reload,
    set,
  };
}
