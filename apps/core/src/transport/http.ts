export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

export interface HttpDeps {
  baseUrl: () => string
  fetch: FetchLike
  token: () => string | null
  refresh: () => Promise<boolean>
  // Optional pre-flight: apps that track their own token expiry refresh once before the
  // first send when this returns true. Omitted callers refresh only reactively on a 401.
  isExpiring?: () => boolean
  // Optional error-body shaping (the mobile gateway hides HTML bodies). Defaults to the
  // server's `{error}` field, else the raw body.
  formatError?: (response: Response, body: string) => string
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export interface HttpClient {
  request: (path: string, init?: RequestInit) => Promise<Response>
  json: <T>(path: string, init?: RequestInit) => Promise<T>
}

function errorMessage(body: string): string {
  try {
    const parsed: unknown = JSON.parse(body)
    if (parsed !== null && typeof parsed === "object" && "error" in parsed) {
      const value = (parsed as Record<string, unknown>).error
      if (typeof value === "string") return value
    }
    return body
  } catch {
    return body
  }
}

export function createHttpClient(deps: HttpDeps): HttpClient {
  const headers = (init?: RequestInit): Headers => {
    const result = new Headers()
    const token = deps.token()
    if (token !== null) result.set("Authorization", `Bearer ${token}`)
    new Headers(init?.headers).forEach((value, key) => {
      result.set(key, value)
    })
    return result
  }

  const send = (path: string, init?: RequestInit): Promise<Response> =>
    deps.fetch(`${deps.baseUrl()}${path}`, { ...init, headers: headers(init) })

  const request = async (path: string, init?: RequestInit): Promise<Response> => {
    if (deps.isExpiring?.()) await deps.refresh()
    let response = await send(path, init)
    if (response.status === 401 && (await deps.refresh())) {
      response = await send(path, init)
    }
    if (!response.ok) {
      const body = await response.text()
      throw new ApiError(
        response.status,
        deps.formatError ? deps.formatError(response, body) : errorMessage(body),
      )
    }
    return response
  }

  return {
    request,
    json: async <T>(path: string, init?: RequestInit): Promise<T> => {
      const response = await request(path, init)
      return (await response.json()) as T
    },
  }
}
