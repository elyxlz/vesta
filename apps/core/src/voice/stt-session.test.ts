import { describe, expect, it } from "vitest"

import {
  createSttSession,
  MAX_PENDING_AUDIO_BYTES,
  type AudioCapture,
  type SttSessionCallbacks,
  type VoiceSocketLike,
} from "./stt-session"

// A socket the test opens by hand, so the pre-open buffer window can be observed.
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
  emit(event: string, transcript?: string): void {
    this.onmessage?.(JSON.stringify({ type: "TurnInfo", event, transcript }))
  }
}

// A capture port that hands the session an onFrame the test drives.
function fakeCapture() {
  let frame: ((pcm: ArrayBuffer) => void) | null = null
  const capture: AudioCapture = {
    start: (onFrame) => {
      frame = onFrame
      return Promise.resolve()
    },
    stop: () => {
      frame = null
    },
  }
  return { capture, send: (n: number) => frame?.(new ArrayBuffer(n)) }
}

function recorder(): SttSessionCallbacks & {
  transcripts: string[]
  turns: string[]
  errors: string[]
  active: boolean[]
} {
  const transcripts: string[] = []
  const turns: string[] = []
  const errors: string[] = []
  const active: boolean[] = []
  return {
    transcripts,
    turns,
    errors,
    active,
    onTranscript: (t) => transcripts.push(t),
    onTurnStart: () => undefined,
    onTurnEnd: (t) => turns.push(t),
    onError: (m) => errors.push(m),
    onActiveChange: (a) => active.push(a),
  }
}

function setup(accumulate: boolean) {
  const socket = new FakeSocket()
  const cap = fakeCapture()
  const cbs = recorder()
  const session = createSttSession(
    {
      buildUrl: () => Promise.resolve("wss://x"),
      createSocket: () => socket,
      capture: cap.capture,
    },
    cbs,
    { accumulate },
  )
  return { socket, cap, cbs, session }
}

const tick = (): Promise<void> => new Promise((r) => setTimeout(r, 0))

describe("the STT session", () => {
  it("buffers frames captured before the socket opens and flushes them in order", async () => {
    const { socket, cap, session } = setup(false)
    const starting = session.start()
    await tick()
    cap.send(10)
    cap.send(20)
    expect(socket.sent).toHaveLength(0)
    socket.onopen?.()
    await starting
    expect(socket.sent.map((f) => f.byteLength)).toEqual([10, 20])
    cap.send(5)
    expect(socket.sent).toHaveLength(3)
  })

  it("keeps only the newest frames up to the pending cap", async () => {
    const { socket, cap, session } = setup(false)
    const starting = session.start()
    await tick()
    const half = MAX_PENDING_AUDIO_BYTES / 2
    cap.send(half)
    cap.send(half)
    cap.send(2)
    socket.onopen?.()
    await starting
    expect(socket.sent.map((f) => f.byteLength)).toEqual([half, 2])
  })

  it("delivers each turn on its own when not accumulating", async () => {
    const { socket, cbs, session } = setup(false)
    const starting = session.start()
    await tick()
    socket.onopen?.()
    await starting
    socket.emit("StartOfTurn")
    socket.emit("Update", "hello")
    socket.emit("EndOfTurn", "hello")
    expect(cbs.turns).toEqual(["hello"])
    expect(cbs.transcripts.at(-1)).toBe("")
  })

  it("closes a turn that transcribed nothing with an empty turn end", async () => {
    const { socket, cbs, session } = setup(false)
    const starting = session.start()
    await tick()
    socket.onopen?.()
    await starting
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn")
    expect(cbs.turns).toEqual([""])
  })

  it("accumulates turns and returns the whole display, partial included, on stop", async () => {
    const { socket, cbs, session } = setup(true)
    const starting = session.start()
    await tick()
    socket.onopen?.()
    await starting
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "hello")
    socket.emit("StartOfTurn")
    socket.emit("Update", "there")
    expect(cbs.transcripts.at(-1)).toBe("hello there")
    expect(session.stop()).toBe("hello there")
  })

  it("drops an in-flight partial on stop instead of sending half a turn", async () => {
    const { socket, cbs, session } = setup(false)
    const starting = session.start()
    await tick()
    socket.onopen?.()
    await starting
    socket.emit("StartOfTurn")
    socket.emit("Update", "half a thought")
    expect(session.stop()).toBe("")
    expect(cbs.turns).toEqual([])
  })

  it("reports a service error and goes inactive", async () => {
    const { socket, cbs, session } = setup(false)
    const starting = session.start()
    await tick()
    socket.onopen?.()
    await starting
    socket.onmessage?.(JSON.stringify({ type: "Error" }))
    expect(cbs.errors).toEqual(["Transcription service error"])
    expect(session.active()).toBe(false)
    expect(cbs.active).toEqual([true, false])
  })

  it("abandons a start the caller stopped before the socket opened", async () => {
    const { cbs, session } = setup(false)
    const starting = session.start()
    await tick()
    expect(session.stop()).toBe("")
    await starting
    expect(cbs.active).toEqual([])
    expect(session.active()).toBe(false)
  })
})
