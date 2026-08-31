import { describe, expect, it, vi } from "vitest"

import {
  createVoiceSession,
  type VoiceMode,
  type VoiceSessionCallbacks,
  type VoiceSessionSettings,
} from "./voice-session"
import type { AudioCapture, VoiceSocketLike } from "./stt-session"
import type { SpeechPlayer } from "./tts-queue"

class FakeSocket implements VoiceSocketLike {
  onopen: (() => void) | null = null
  onmessage: ((data: string) => void) | null = null
  onclose: ((reason: string) => void) | null = null
  send(): void {
    /* not asserted here */
  }
  close(): void {
    /* noop */
  }
  emit(event: string, transcript?: string): void {
    this.onmessage?.(JSON.stringify({ type: "TurnInfo", event, transcript }))
  }
}

function fakeCapture(): AudioCapture {
  return {
    start: (onFrame) => {
      void onFrame
      return Promise.resolve()
    },
    stop: () => undefined,
  }
}

function recorder() {
  const events = {
    transcripts: [] as string[],
    sends: [] as string[],
    errors: [] as string[],
    modes: [] as (VoiceMode | null)[],
    listening: [] as boolean[],
    speaking: [] as boolean[],
    userSpeaking: [] as boolean[],
    inactivity: 0,
  }
  const callbacks: VoiceSessionCallbacks = {
    onTranscript: (t) => events.transcripts.push(t),
    onSend: (t) => events.sends.push(t),
    onError: (m) => events.errors.push(m),
    onModeChange: (m) => events.modes.push(m),
    onListeningChange: (l) => events.listening.push(l),
    onSpeakingChange: (s) => events.speaking.push(s),
    onUserSpeakingChange: (s) => events.userSpeaking.push(s),
    onInactivityStop: () => (events.inactivity += 1),
  }
  return { events, callbacks }
}

function setup(overrides: Partial<VoiceSessionSettings> = {}) {
  const socket = new FakeSocket()
  const player: SpeechPlayer = {
    prepare: (t) => Promise.resolve(t),
    play: (_id, signal) =>
      new Promise<void>((_resolve, reject) => {
        signal.addEventListener("abort", () => {
          reject(new Error("aborted"))
        })
      }),
  }
  const timers = new Map<number, () => void>()
  let nextTimer = 1
  const { events, callbacks } = recorder()
  const settings: VoiceSessionSettings = {
    interruptTts: true,
    inactivityMs: 1000,
    yieldToUser: true,
    ...overrides,
  }
  const session = createVoiceSession(
    {
      buildUrl: () => Promise.resolve("wss://x"),
      createSocket: () => socket,
      capture: fakeCapture(),
      player,
      setTimer: (fn) => {
        const id = nextTimer++
        timers.set(id, fn)
        return id
      },
      clearTimer: (id) => timers.delete(id),
    },
    callbacks,
    () => settings,
  )
  const startAnd = async (mode: VoiceMode) => {
    const p = session.start(mode)
    await new Promise((r) => setTimeout(r, 0))
    socket.onopen?.()
    await p
  }
  const fireTimers = () => {
    for (const fn of [...timers.values()]) fn()
  }
  return { socket, session, events, settings, startAnd, fireTimers }
}

describe("the voice session", () => {
  it("marks the mode before the microphone opens and clears it on stop", async () => {
    const { session, events } = setup()
    const p = session.start("dictation")
    expect(events.modes).toEqual(["dictation"])
    expect(session.mode()).toBe("dictation")
    session.stop()
    await p
    expect(events.modes).toEqual(["dictation", null])
  })

  it("dictation accumulates turns and sends one message on confirm", async () => {
    const { socket, session, events, startAnd } = setup()
    await startAnd("dictation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "buy milk")
    socket.emit("StartOfTurn")
    socket.emit("Update", "and eggs")
    expect(events.sends).toEqual([])
    session.stop()
    expect(events.sends).toEqual(["buy milk and eggs"])
  })

  it("dictation cancel sends nothing", async () => {
    const { socket, session, events, startAnd } = setup()
    await startAnd("dictation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "never mind")
    session.cancel()
    expect(events.sends).toEqual([])
    expect(session.mode()).toBeNull()
  })

  it("a conversation sends each turn as it ends and keeps listening", async () => {
    const { socket, session, events, startAnd } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "first")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "second")
    expect(events.sends).toEqual(["first", "second"])
    expect(session.mode()).toBe("conversation")
  })

  it("a conversation cuts a reply on a user turn even when interruptTts is off", async () => {
    const { socket, session, startAnd } = setup({ interruptTts: false })
    await startAnd("conversation")
    session.speak("a long reply")
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true)
    })
    socket.emit("StartOfTurn")
    expect(session.speaking()).toBe(false)
  })

  it("dictation leaves a reply alone on a user turn when interruptTts is off", async () => {
    const { socket, session, startAnd } = setup({ interruptTts: false })
    await startAnd("dictation")
    session.speak("a long reply")
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true)
    })
    socket.emit("StartOfTurn")
    expect(session.speaking()).toBe(true)
  })

  it("a silent conversation ends itself and reports the inactivity stop", async () => {
    const { socket, session, events, startAnd, fireTimers } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "last words")
    fireTimers()
    expect(session.mode()).toBeNull()
    expect(events.inactivity).toBe(1)
  })

  it("dictation arms no inactivity timer", async () => {
    const { session, events, startAnd, fireTimers } = setup()
    await startAnd("dictation")
    fireTimers()
    expect(session.mode()).toBe("dictation")
    expect(events.inactivity).toBe(0)
  })

  it("a yielding conversation reports the user's turn and closes it on turn end", async () => {
    const { socket, events, startAnd } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    expect(events.userSpeaking).toEqual([true])
    socket.emit("EndOfTurn", "hello")
    expect(events.userSpeaking).toEqual([true, false])
    expect(events.sends).toEqual(["hello"])
  })

  it("an empty turn still closes the user's turn and sends nothing", async () => {
    const { socket, events, startAnd } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn")
    expect(events.userSpeaking).toEqual([true, false])
    expect(events.sends).toEqual([])
  })

  it("holds a reply arriving mid-turn and speaks it once the turn ends", async () => {
    const { socket, session, startAnd } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    session.speak("held reply")
    expect(session.speaking()).toBe(false)
    socket.emit("EndOfTurn", "go on")
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true)
    })
  })

  it("drops a held reply when the session ends mid-turn", async () => {
    const { socket, session, events, startAnd } = setup()
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    session.speak("held reply")
    session.cancel()
    await new Promise((r) => setTimeout(r, 0))
    expect(session.speaking()).toBe(false)
    expect(events.userSpeaking).toEqual([true, false])
  })

  it("yieldToUser off neither reports nor holds", async () => {
    const { socket, session, events, startAnd } = setup({ yieldToUser: false })
    await startAnd("conversation")
    socket.emit("StartOfTurn")
    session.speak("straight through")
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true)
    })
    expect(events.userSpeaking).toEqual([])
  })

  it("dictation never reports the user's turn", async () => {
    const { socket, session, events, startAnd } = setup()
    await startAnd("dictation")
    socket.emit("StartOfTurn")
    socket.emit("EndOfTurn", "noted")
    session.stop()
    expect(events.userSpeaking).toEqual([])
  })

  it("reports listening once the socket is up", async () => {
    const { session, events, startAnd } = setup()
    expect(session.listening()).toBe(false)
    await startAnd("conversation")
    expect(session.listening()).toBe(true)
    expect(events.listening).toContain(true)
  })
})
