import type { FetchLike } from "../transport/http"
import type { ReleaseChannel } from "../protocol/tree"
import { compareReleaseVersions } from "../protocol/release-version"

const WHATS_NEW_BLOCK_RE = /<!--\s*whats-new\s*-->([\s\S]*?)<!--\s*\/whats-new\s*-->/

const RELEASES_URL = "https://api.github.com/repos/elyxlz/vesta/releases?per_page=20"

const RELEASES_FETCH_TIMEOUT_MS = 10_000

export interface ReleaseNote {
  version: string
  date: string
  prerelease: boolean
  message: string
}

interface GithubRelease {
  tag_name: string
  published_at: string
  prerelease: boolean
  body: string
}

function isGithubRelease(value: unknown): value is GithubRelease {
  return (
    typeof value === "object" &&
    value !== null &&
    "tag_name" in value &&
    typeof value.tag_name === "string" &&
    "published_at" in value &&
    typeof value.published_at === "string" &&
    "prerelease" in value &&
    typeof value.prerelease === "boolean" &&
    "body" in value &&
    typeof value.body === "string"
  )
}

export function extractWhatsNew(body: string): string | null {
  const match = WHATS_NEW_BLOCK_RE.exec(body)
  if (!match) return null
  const message = match[1]?.trim() ?? ""
  return message.length > 0 ? message : null
}

/** Parse a GitHub release-list response into notes, newest version first. */
export function parseReleaseNotes(json: unknown): ReleaseNote[] {
  if (!Array.isArray(json)) return []
  const notes: ReleaseNote[] = []
  for (const release of json as unknown[]) {
    if (!isGithubRelease(release)) continue
    const message = extractWhatsNew(release.body)
    if (message === null) continue
    notes.push({
      version: release.tag_name.replace(/^v/, ""),
      date: release.published_at,
      prerelease: release.prerelease,
      message,
    })
  }
  return notes.sort((a, b) => compareReleaseVersions(b.version, a.version) ?? 0)
}

/**
 * Keep only notes the connected vestad has actually shipped: versions at or
 * below the running one, with prereleases visible only on the beta channel.
 */
export function filterReleaseNotes(
  notes: ReleaseNote[],
  connected: { version: string; channel: ReleaseChannel },
): ReleaseNote[] {
  return notes.filter((note) => {
    const comparison = compareReleaseVersions(note.version, connected.version)
    return (
      comparison !== null && comparison <= 0 && (connected.channel === "beta" || !note.prerelease)
    )
  })
}

/** Fetch and parse the release list; null on any network or HTTP failure. */
export async function fetchReleaseNotes(fetcher: FetchLike = fetch): Promise<ReleaseNote[] | null> {
  const controller = new AbortController()
  const timeout = setTimeout(() => {
    controller.abort()
  }, RELEASES_FETCH_TIMEOUT_MS)
  try {
    const response = await fetcher(RELEASES_URL, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    })
    if (!response.ok) return null
    return parseReleaseNotes(await response.json())
  } catch {
    return null
  } finally {
    clearTimeout(timeout)
  }
}
