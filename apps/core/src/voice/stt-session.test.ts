import { describe, expect, it } from "vitest"

import {
  createSttSession,
  MAX_PENDING_AUDIO_BYTES,
  type AudioCapture,
  type SttSessionCallbacks,
  type VoiceSocketLike,
} from "./stt-session"

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
    this.onopen?.()
  }
  message(payload: object): void {
    this.onmessage?.(JSON.stringify(payload))
  }
}

class FakeCapture implements AudioCapture {
  onFrame: ((pcm: ArrayBuffer) => void) | null = null
  stopped = false

  start(onFrame: (pcm: ArrayBuffer) => void): Promise<void> {
    this.onFrame = onFrame
    return Promise.resolve()
  }
  stop(): void {
    this.stopped = true
  }
  emit(bytes: number, fill = 0): void {
    const frame = new ArrayBuffer(bytes)
    new Uint8Array(frame).fill(fill)
    this.onFrame?.(frame)
  }
}

interface Recorded {
  transcripts: string[]
  turnStarts: number
  turnEnds: string[]
  errors: string[]
  activeChanges: boolean[]
  order: string[]
}

function recorder(): { callbacks: SttSessionCallbacks; recorded: Recorded } {
  const recorded: Recorded = {
    transcripts: [],
    turnStarts: 0,
    turnEnds: [],
    errors: [],
    activeChanges: [],
    order: [],
  }
  return {
    recorded,
    callbacks: {
      onTranscript: (text) => {
        recorded.transcripts.push(text)
        recorded.order.push(`transcript:${text}`)
      },
      onTurnStart: () => {
        recorded.turnStarts += 1
      },
      onTurnEnd: (text) => {
        recorded.turnEnds.push(text)
        recorded.order.push(`turnEnd:${text}`)
      },
      onError: (message) => recorded.errors.push(message),
      onActiveChange: (active) => recorded.activeChanges.push(active),
    },
  }
}

function harness(options: { accumulate?: boolean } = {}): {
  socket: FakeSocket
  capture: FakeCapture
  recorded: Recorded
  session: ReturnType<typeof createSttSession>
} {
  const socket = new FakeSocket()
  const capture = new FakeCapture()
  const { callbacks, recorded } = recorder()
  const session = createSttSession(
    {
      buildUrl: () => Promise.resolve("wss://gateway/stt"),
      createSocket: () => socket,
      capture,
    },
    callbacks,
    options,
  )
  return { socket, capture, recorded, session }
}

async function startOpen(h: ReturnType<typeof harness>): Promise<void> {
  const started = h.session.start()
  await Promise.resolve()
  await Promise.resolve()
  h.socket.open()
  await started
}

describe("createSttSession", () => {
  it("buffers frames captured before the socket opens and flushes them in order", async () => {
    const h = harness()
    const started = h.session.start()
    await Promise.resolve()
    await Promise.resolve()

    h.capture.emit(4, 1)
    h.capture.emit(4, 2)
    expect(h.socket.sent).toHaveLength(0)

    h.socket.open()
    await started

    expect(h.socket.sent.map((b) => new Uint8Array(b)[0])).toEqual([1, 2])
    h.capture.emit(4, 3)
    expect(h.socket.sent).toHaveLength(3)
    expect(h.session.active()).toBe(true)
  })

  it("drops the oldest buffered audio past the pending cap", async () => {
    const h = harness()
    const started = h.session.start()
    await Promise.resolve()
    await Promise.resolve()

    const third = Math.floor(MAX_PENDING_AUDIO_BYTES / 2)
    h.capture.emit(third, 1)
    h.capture.emit(third, 2)
    h.capture.emit(third, 3)

    h.socket.open()
    await started

    expect(h.socket.sent.map((b) => new Uint8Array(b)[0])).toEqual([2, 3])
  })

  it("forwards transcripts", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: "hello" })

    expect(h.recorded.transcripts).toEqual(["hello"])
  })

  it("signals turn start and resets the transcript", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: "hel" })
    h.socket.message({ type: "TurnInfo", event: "StartOfTurn" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })

    expect(h.recorded.turnStarts).toBe(1)
    expect(h.recorded.turnEnds).toEqual([])
  })

  it("ends a turn with the trimmed transcript, clearing the display first", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: " hello there " })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })

    // The display clears before the turn is delivered, so a consumer that
    // renders the transcript into a draft box gets the final text last.
    expect(h.recorded.order).toEqual([
      "transcript: hello there ",
      "transcript:",
      "turnEnd:hello there",
    ])
  })

  it("accumulates committed turns across turn ends", async () => {
    const h = harness({ accumulate: true })
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: "one" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })
    h.socket.message({ type: "TurnInfo", transcript: "two" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })

    expect(h.recorded.turnEnds).toEqual(["one", "two"])
    expect(h.recorded.transcripts).toEqual(["one", "one", "one two", "one two"])
  })

  it("stop flushes the pending transcript as a final turn", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: "bye" })
    const finalText = h.session.stop()

    expect(finalText).toBe("bye")
    expect(h.recorded.turnEnds).toEqual(["bye"])
    expect(h.session.active()).toBe(false)
    expect(h.capture.stopped).toBe(true)
    expect(h.socket.closed).toBe(true)
    expect(h.recorded.activeChanges).toEqual([true, false])
  })

  it("stop returns the full spoken text in accumulate mode", async () => {
    const h = harness({ accumulate: true })
    await startOpen(h)

    h.socket.message({ type: "TurnInfo", transcript: "one" })
    h.socket.message({ type: "TurnInfo", event: "EndOfTurn" })
    h.socket.message({ type: "TurnInfo", transcript: "two" })
    const finalText = h.session.stop()

    expect(finalText).toBe("one two")
    expect(h.recorded.turnEnds).toEqual(["one"])
  })

  it("a service error ends the session", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.message({ type: "Error" })

    expect(h.recorded.errors).toEqual(["Transcription service error"])
    expect(h.session.active()).toBe(false)
    expect(h.capture.stopped).toBe(true)
  })

  it("an unexpected close ends the session with an error", async () => {
    const h = harness()
    await startOpen(h)

    h.socket.onclose?.("gone")

    expect(h.recorded.errors).toEqual(["Transcription connection closed unexpectedly"])
    expect(h.session.active()).toBe(false)
    expect(h.capture.stopped).toBe(true)
  })

  it("start rejects when the socket closes before opening", async () => {
    const h = harness()
    const started = h.session.start()
    await Promise.resolve()
    await Promise.resolve()

    h.socket.onclose?.("refused")

    await expect(started).rejects.toThrow("Could not connect to live transcription")
    expect(h.session.active()).toBe(false)
    expect(h.capture.stopped).toBe(true)
  })

  it("start while active is a no-op", async () => {
    const h = harness()
    await startOpen(h)

    await h.session.start()

    expect(h.recorded.activeChanges).toEqual([true])
  })
})
