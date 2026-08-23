import { useEffect, useRef, useState } from "react"
import type { GatewayOperation } from "../protocol/tree"

// How long the "updated to vX.Y.Z" resolution stays up before the app returns to normal.
export const UPDATED_NOTICE_MS = 6000

// Resolve the update the user watched: remember the version it started from, and once the operation
// clears against a different one, report it for a moment. Timing rather than derivable state, so it
// lives in an Effect with its own cleanup. A restart lands on the same version, so it resolves to
// nothing, which is exactly right. Every platform that renders the operation renders this too, which
// is what makes the gateway's own `gateway_updated` notification the unwatched case alone.
export function useUpdateResolution(
  operation: GatewayOperation | null,
  version: string,
): string | null {
  const versionBeforeUpdate = useRef("")
  const [updatedTo, setUpdatedTo] = useState<string | null>(null)
  useEffect(() => {
    // The empty version is "no gateway branch yet", which resolves nothing either way.
    if (operation !== null) {
      // A new operation supersedes a still-showing notice.
      setUpdatedTo(null)
      if (versionBeforeUpdate.current === "") versionBeforeUpdate.current = version
      return
    }
    const before = versionBeforeUpdate.current
    versionBeforeUpdate.current = ""
    if (before === "" || version === "" || before === version) return
    setUpdatedTo(version)
    const clear = setTimeout(() => {
      setUpdatedTo(null)
    }, UPDATED_NOTICE_MS)
    return () => {
      clearTimeout(clear)
    }
  }, [operation, version])
  return updatedTo
}

// Resolve the restart the user watched: once a restart operation clears without failing, report it
// for the same moment. A restart changes no version, so this is the only way it gets a landing.
export function useRestartResolution(operation: GatewayOperation | null): boolean {
  const watching = useRef(false)
  const [restarted, setRestarted] = useState(false)
  useEffect(() => {
    if (operation !== null) {
      setRestarted(false)
      watching.current = operation.kind === "restart" && operation.phase !== "failed"
      return
    }
    if (!watching.current) return
    watching.current = false
    setRestarted(true)
    const clear = setTimeout(() => {
      setRestarted(false)
    }, UPDATED_NOTICE_MS)
    return () => {
      clearTimeout(clear)
    }
  }, [operation])
  return restarted
}
