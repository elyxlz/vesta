// The behavior model over one microphone and one speaker: composes the STT
// session and the TTS queue and owns the decisions both apps must agree on —
// barge-in (a user turn interrupts playback per interrupt_tts), auto_send
// routing (send vs draft), hold-to-talk accumulation, and the idle auto-stop.
// Apps adapt audio I/O and render the state; they no longer decide.

import {
  createSttSession,
  type AudioCapture,
  type SttSession,
  type VoiceSocketLike,
} from "./stt-session"
import { createTtsQueue, type SpeechPlayer, type TtsQueue } from "./tts-queue"

export interface VoiceSessionSettings {
  autoSend: boolean
  interruptTts: boolean
  // Hold-to-talk: turns accumulate and one send fires on stop. Captured at
  // listen start; autoSend and interruptTts are read live per event.
  hold: boolean
  // 0 disables. Ignored in hold mode, where release is the stop.
  idleTimeoutMs: number
}

export interface VoiceSessionDeps {
  buildUrl: () => Promise<string>
  createSocket: (url: string) => VoiceSocketLike
  capture: AudioCapture
  player: SpeechPlayer
  setTimer: (fn: () => void, ms: number) => number
  clearTimer: (handle: number) => void
}

export interface VoiceSessionCallbacks {
  onTranscript: (text: string) => void
  onSend: (text: string) => void
  onDraft: (text: string) => void
  onError: (message: string) => void
  onListeningChange: (listening: boolean) => void
  onSpeakingChange: (speaking: boolean) => void
}

export interface VoiceSession {
  startListening: () => Promise<void>
  stopListening: () => void
  listening: () => boolean
  speak: (text: string) => void
  prefetch: (text: string) => void
  stopSpeech: () => void
  speaking: () => boolean
}

export function createVoiceSession(
  deps: VoiceSessionDeps,
  callbacks: VoiceSessionCallbacks,
  settings: () => VoiceSessionSettings,
): VoiceSession {
  let stt: SttSession | null = null
  let idleTimer: number | null = null

  const queue: TtsQueue = createTtsQueue(deps.player, {
    onSpeakingChange: callbacks.onSpeakingChange,
    onError: callbacks.onError,
  })

  const clearIdleTimer = (): void => {
    if (idleTimer !== null) {
      deps.clearTimer(idleTimer)
      idleTimer = null
    }
  }

  // The session started in hold mode, if any: stopListening must know whether
  // the text it flushed is the one hold-to-talk sends on release.
  let holdSession: SttSession | null = null

  const stopListening = (): void => {
    clearIdleTimer()
    const session = stt
    if (!session) return
    stt = null
    const hold = session === holdSession
    holdSession = null
    const full = session.stop()
    if (hold && full) callbacks.onSend(full)
  }

  const startListening = async (): Promise<void> => {
    if (stt) return
    const { hold, idleTimeoutMs } = settings()
    queue.stop()

    const armIdleTimer = (): void => {
      if (hold || !idleTimeoutMs) return
      clearIdleTimer()
      idleTimer = deps.setTimer(() => {
        idleTimer = null
        stopListening()
      }, idleTimeoutMs)
    }

    const session = createSttSession(
      {
        buildUrl: deps.buildUrl,
        createSocket: deps.createSocket,
        capture: deps.capture,
      },
      {
        onTranscript: (text) => {
          callbacks.onTranscript(text)
          if (text && !hold && !settings().autoSend) callbacks.onDraft(text)
          if (text) armIdleTimer()
        },
        onTurnStart: () => {
          if (settings().interruptTts) queue.stop()
        },
        onTurnEnd: (text) => {
          if (!hold) {
            if (settings().autoSend) callbacks.onSend(text)
            else callbacks.onDraft(text)
          }
          armIdleTimer()
        },
        onError: callbacks.onError,
        onActiveChange: (active) => {
          if (!active && stt === session) {
            stt = null
            holdSession = null
            clearIdleTimer()
          }
          callbacks.onListeningChange(active)
        },
      },
      { accumulate: hold },
    )

    stt = session
    holdSession = hold ? session : null
    try {
      await session.start()
    } catch (cause) {
      if (stt === session) {
        stt = null
        holdSession = null
      }
      throw cause
    }
    armIdleTimer()
  }

  return {
    startListening,
    stopListening,
    listening: () => stt?.active() ?? false,
    speak: (text) => {
      queue.speak(text)
    },
    prefetch: (text) => {
      queue.prefetch(text)
    },
    stopSpeech: () => {
      queue.stop()
    },
    speaking: () => queue.speaking(),
  }
}
