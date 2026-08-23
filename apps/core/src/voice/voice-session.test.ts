import { describe, expect, it } from "vitest"

import { createVoiceSession, type VoiceSessionSettings } from "./voice-session"
import type { AudioCapture, VoiceSocketLike } from "./stt-session"
import type { SpeechPlayer } from "./tts-queue"

class FakeSocket implements VoiceSocketLike {
  sent: ArrayBuffer[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((data: string) => void) | null = null
  onclose: ((reason: string) => void) | null = null
  send(data: ArrayBuffer): void {
    this.sent.push(data)
  }
  close(): void {
    this.closed = true
  }
  open(): void {
    this.closed = false
    this.onopen?.()
  }
  message(payload: object): void {
    this.onmessage?.(JSON.stringify(payload))
  }
}

class FakeCapture implements AudioCapture {
  stopped = false
  start(): Promise<void> {
    this.stopped = false
    return Promise.resolve()
  }
  stop(): void {
    this.stopped = true
  }
}

interface PlayCall {
  id: string
  signal: AbortSignal
  finish: () => void
}

class FakeTimers {
  pending = new Map<number, () => void>()
  delays: number[] = []
  private next = 1
  set = (fn: () => void, ms: number): number => {
    const handle = this.next++
    this.delays.push(ms)
    this.pending.set(handle, fn)
    return handle
  }
  clear = (handle: number): void => {
    this.pending.delete(handle)
  }
  fire(): void {
    const fns = [...this.pending.values()]
    this.pending.clear()
    for (const fn of fns) fn()
  }
}

interface Recorded {
  transcripts: string[]
  sends: string[]
  drafts: string[]
  errors: string[]
  listening: boolean[]
}

function harness(initial: Partial<VoiceSessionSettings> = {}): {
  socket: FakeSocket
  settings: VoiceSessionSettings
  timers: FakeTimers
  plays: PlayCall[]
  recorded: Recorded
  session: ReturnType<typeof createVoiceSession>
  startOpen: () => Promise<void>
} {
  const socket = new FakeSocket()
  const timers = new FakeTimers()
  const plays: PlayCall[] = []
  const player: SpeechPlayer = {
    prepare: (text) => Promise.resolve(`id:${text}`),
    play: (id, signal) =>
      new Promise<void>((resolve) => {
        signal.addEventListener("abort", () => {
          resolve()
        })
        plays.push({
          id,
          signal,
          finish: () => {
            resolve()
          },
        })
      }),
  }
  const settings: VoiceSessionSettings = {
    autoSend: true,
    interruptTts: true,
    hold: false,
    idleTimeoutMs: 0,
    ...initial,
  }
  const recorded: Recorded = {
    transcripts: [],
    sends: [],
    drafts: [],
    errors: [],
    listening: [],
  }
  const session = createVoiceSession(
    {
      buildUrl: () => Promise.resolve("wss://gateway/stt"),
      createSocket: () => socket,
      capture: new FakeCapture(),
      player,
      setTimer: timers.set,
      clearTimer: timers.clear,
    },
    {
      onTranscript: (text) => recorded.transcripts.push(text),
      onSend: (text) => recorded.sends.push(text),
      onDraft: (text) => recorded.drafts.push(text),
      onError: (message) => recorded.errors.push(message),
      onListeningChange: (listening) => recorded.listening.push(listening),
      onSpeakingChange: () => undefined,
    },
    () => ({ ...settings }),
  )
  const startOpen = async (): Promise<void> => {
    const started = session.startListening()
    await Promise.resolve()
    await Promise.resolve()
    socket.open()
    await started
  }
  return { socket, settings, timers, plays, recorded, session, startOpen }
}

const tick = (): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, 0)
  })

describe("createVoiceSession", () => {
  it("starting to listen stops speech first", async () => {
    const h = harness()
    h.session.speak("reply")
    await tick()
    expect(h.plays[0]?.signal.aborted).toBe(false)

    await h.startOpen()

    expect(h.plays[0]?.signal.aborted).toBe(true)
  })

  it("a user turn interrupts playback when interrupt_tts is on", async () => {
    const h = harness()
    await h.startOpen()
    h.session.speak("reply")
    await tick()

    h.socket.message({ type: "TurnInfo", event: "StartOfTurn" })

    expect(h.plays[0]?.signal.aborted).toBe(true)
  })

  it("keeps playing through a user turn when interrupt_tts is off", async () => {
    const h = harness({ interruptTts: false })
    await h.startOpen()
    h.session.speak("reply")
    await tick()

    h.socket.message({ type: "TurnInfo", event: "StartOfTurn" })

    expect(h.plays[0]?.signal.aborted).toBe(false)
  })

  it("sends the finished turn when auto-send is on", async () => {
    const h = harness()
    await h.startOpen()

    h.socket.message({ type: "TurnInfo", transcript: "hello" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })

    expect(h.recorded.sends).toEqual(["hello"])
    expect(h.recorded.drafts).toEqual([])
  })

  it("drafts the finished turn when auto-send is off", async () => {
    const h = harness({ autoSend: false })
    await h.startOpen()

    h.socket.message({ type: "TurnInfo", transcript: "hello" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })

    expect(h.recorded.sends).toEqual([])
    expect(h.recorded.drafts.at(-1)).toBe("hello")
  })

  it("hold mode sends the accumulated text once on stop", async () => {
    const h = harness({ hold: true })
    await h.startOpen()

    h.socket.message({ type: "TurnInfo", transcript: "one" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })
    h.socket.message({ type: "TurnInfo", transcript: "two" })
    expect(h.recorded.sends).toEqual([])

    h.session.stopListening()

    expect(h.recorded.sends).toEqual(["one two"])
    expect(h.session.listening()).toBe(false)
  })

  it("auto-stops after the idle timeout", async () => {
    const h = harness({ idleTimeoutMs: 5000 })
    await h.startOpen()
    expect(h.session.listening()).toBe(true)

    h.timers.fire()

    expect(h.session.listening()).toBe(false)
    expect(h.recorded.listening).toEqual([true, false])
  })

  it("does not arm the idle timeout in hold mode", async () => {
    const h = harness({ hold: true, idleTimeoutMs: 5000 })
    await h.startOpen()

    expect(h.timers.pending.size).toBe(0)
  })

  it("forwards transcription errors and the listening state", async () => {
    const h = harness()
    await h.startOpen()

    h.socket.message({ type: "Error" })

    expect(h.recorded.errors).toEqual(["Transcription service error"])
    expect(h.recorded.listening).toEqual([true, false])
    expect(h.session.listening()).toBe(false)
  })

  it("listens again after a stop", async () => {
    const h = harness()
    await h.startOpen()
    h.session.stopListening()

    await h.startOpen()

    expect(h.session.listening()).toBe(true)
  })
})
