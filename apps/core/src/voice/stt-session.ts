// One live transcription session over the voice service's /stt/listen socket,
// shared by web and mobile: the socket lifecycle, the Deepgram TurnInfo protocol,
// transcript accumulation, and the pre-open audio buffer. Platforms inject only
// how audio is captured and how the socket is dialed.

// ~2 seconds of 16 kHz 16-bit mono audio: frames captured before the socket
// opens are kept up to this, oldest dropped first.
export const MAX_PENDING_AUDIO_BYTES = 16_000 * 2 * 2

export interface VoiceSocketLike {
  send: (data: ArrayBuffer) => void
  close: () => void
  onopen: (() => void) | null
  onmessage: ((data: string) => void) | null
  onclose: ((reason: string) => void) | null
}

export interface AudioCapture {
  // Starts the microphone and resolves once frames can flow; frames are raw
  // 16 kHz 16-bit mono PCM. Rejecting is the permission/hardware failure path.
  start: (onFrame: (pcm: ArrayBuffer) => void) => Promise<void>
  stop: () => void
}

export interface SttSessionDeps {
  // Async and re-asked on every start, so the service key in the URL is minted
  // or refreshed at dial time rather than captured at construction.
  buildUrl: () => Promise<string>
  createSocket: (url: string) => VoiceSocketLike
  capture: AudioCapture
}

export interface SttSessionCallbacks {
  onTranscript: (text: string) => void
  onTurnStart: () => void
  onTurnEnd: (text: string) => void
  onError: (message: string) => void
  onActiveChange: (active: boolean) => void
}

export interface SttSessionOptions {
  // Hold-to-talk: committed turns concatenate into one growing transcript that
  // stop() returns, instead of each turn ending on its own.
  accumulate?: boolean
}

export interface SttSession {
  start: () => Promise<void>
  // Ends the session and returns the full text spoken so far (empty when idle).
  stop: () => string
  active: () => boolean
}

interface TurnInfoEvent {
  type?: string
  event?: string
  transcript?: string
}

export function createSttSession(
  deps: SttSessionDeps,
  callbacks: SttSessionCallbacks,
  options: SttSessionOptions = {},
): SttSession {
  const accumulate = options.accumulate ?? false
  let state: "idle" | "starting" | "active" = "idle"
  // Bumped by stop; a start still in flight compares its own generation and
  // abandons quietly instead of throwing at the caller that asked to stop.
  let generation = 0
  let socket: VoiceSocketLike | null = null
  let socketOpen = false
  let rejectOpen: ((reason: Error) => void) | null = null
  let pending: ArrayBuffer[] = []
  let pendingBytes = 0
  let current = ""
  let committed = ""

  const displayText = (): string =>
    accumulate && committed ? (current ? `${committed} ${current}` : committed) : current

  const cleanup = (): void => {
    const wasActive = state === "active"
    state = "idle"
    socketOpen = false
    pending = []
    pendingBytes = 0
    if (socket) {
      socket.onopen = null
      socket.onmessage = null
      socket.onclose = null
      socket.close()
      socket = null
    }
    deps.capture.stop()
    rejectOpen?.(new Error("Could not connect to live transcription"))
    rejectOpen = null
    if (wasActive) callbacks.onActiveChange(false)
  }

  const fail = (message: string): void => {
    cleanup()
    callbacks.onError(message)
  }

  const onFrame = (frame: ArrayBuffer): void => {
    if (state === "idle") return
    if (socket && socketOpen) {
      socket.send(frame)
      return
    }
    while (pending.length > 0 && pendingBytes + frame.byteLength > MAX_PENDING_AUDIO_BYTES) {
      const dropped = pending.shift()
      pendingBytes -= dropped?.byteLength ?? 0
    }
    if (frame.byteLength <= MAX_PENDING_AUDIO_BYTES) {
      pending.push(frame)
      pendingBytes += frame.byteLength
    }
  }

  const handleMessage = (data: string): void => {
    let event: TurnInfoEvent
    try {
      event = JSON.parse(data) as TurnInfoEvent
    } catch {
      return
    }
    if (event.type === "TurnInfo") {
      if (event.event === "StartOfTurn") {
        current = ""
        callbacks.onTurnStart()
      }
      if (event.transcript) {
        current = event.transcript
        callbacks.onTranscript(displayText())
      }
      if (event.event === "EndOfTurn") {
        const text = current.trim()
        current = ""
        if (!text) return
        if (accumulate) {
          committed = committed ? `${committed} ${text}` : text
          callbacks.onTranscript(committed)
        } else {
          // Clear the display before delivering the turn, so a consumer that
          // renders the transcript into a draft box gets the final text last.
          callbacks.onTranscript("")
        }
        callbacks.onTurnEnd(text)
      }
      return
    }
    if (event.type === "ConfigureFailure") fail("Transcription configuration error")
    else if (event.type === "Error") fail("Transcription service error")
  }

  const start = async (): Promise<void> => {
    if (state !== "idle") return
    state = "starting"
    const myGeneration = ++generation
    current = ""
    committed = ""
    pending = []
    pendingBytes = 0

    try {
      const url = await deps.buildUrl()
      if (generation !== myGeneration) return
      const dialed = deps.createSocket(url)
      socket = dialed
      const opened = new Promise<void>((resolve, reject) => {
        rejectOpen = reject
        dialed.onopen = () => {
          rejectOpen = null
          socketOpen = true
          const buffered = pending
          pending = []
          pendingBytes = 0
          for (const frame of buffered) dialed.send(frame)
          resolve()
        }
      })
      dialed.onmessage = handleMessage
      dialed.onclose = () => {
        if (socket !== dialed) return
        if (!socketOpen) {
          const reject = rejectOpen
          rejectOpen = null
          reject?.(new Error("Could not connect to live transcription"))
          return
        }
        fail("Transcription connection closed unexpectedly")
      }
      await Promise.all([deps.capture.start(onFrame), opened])
      if (generation !== myGeneration) return
      state = "active"
      callbacks.onActiveChange(true)
    } catch (cause) {
      cleanup()
      if (generation !== myGeneration) return
      throw cause
    }
  }

  const stop = (): string => {
    if (state === "idle") return ""
    generation += 1
    const full = displayText().trim()
    if (!accumulate) {
      const text = current.trim()
      current = ""
      if (text) {
        callbacks.onTranscript("")
        callbacks.onTurnEnd(text)
      }
    }
    cleanup()
    return full
  }

  return { start, stop, active: () => state === "active" }
}
