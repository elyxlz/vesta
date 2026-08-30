// The one TTS playback pipeline every client drives: an ordered queue over an injected
// player, so consecutive agent replies play back to back instead of cutting each other
// off. Prefetch warms the prepare step during the typing-pacing delay, so playback starts
// the streamed GET the moment a message is revealed.

export interface SpeechPlayer {
  // Registers the text with the voice service and resolves the utterance id.
  prepare: (text: string) => Promise<string>
  // Streams one prepared utterance to the speaker. Resolves when playback ends or the
  // signal aborts; rejects only on a real playback failure.
  play: (id: string, signal: AbortSignal) => Promise<void>
}

export interface TtsQueueCallbacks {
  onSpeakingChange?: (speaking: boolean) => void
  onError?: (message: string) => void
}

export interface TtsQueue {
  speak: (text: string) => void
  prefetch: (text: string) => void
  stop: () => void
  speaking: () => boolean
}

export function createTtsQueue(player: SpeechPlayer, callbacks: TtsQueueCallbacks): TtsQueue {
  let queue: string[] = []
  let processing = false
  let isSpeaking = false
  let abort: AbortController | null = null
  // Bumped by stop to invalidate an in-flight drain loop, so a stop-then-speak sequence
  // never leaves two loops draining the queue at once.
  let epoch = 0
  const prefetched = new Map<string, Promise<string>>()

  const setSpeaking = (speaking: boolean): void => {
    if (isSpeaking === speaking) return
    isSpeaking = speaking
    callbacks.onSpeakingChange?.(speaking)
  }

  const drain = async (): Promise<void> => {
    if (processing) return
    processing = true
    const myEpoch = epoch
    setSpeaking(true)

    while (queue.length > 0 && epoch === myEpoch) {
      const text = queue.shift()
      if (text === undefined) break
      const controller = new AbortController()
      abort = controller
      try {
        const cached = prefetched.get(text)
        prefetched.delete(text)
        const preparedId = cached ? await cached.catch(() => null) : null
        const id = preparedId ?? (await player.prepare(text))
        if (epoch !== myEpoch) break
        await player.play(id, controller.signal)
      } catch {
        if (!controller.signal.aborted) callbacks.onError?.("Voice playback failed")
      }
      if (abort === controller) abort = null
    }

    // A newer epoch (stop) superseded this loop; the new loop owns the shared flags, so
    // exit without resetting them.
    if (epoch !== myEpoch) return

    processing = false
    if (queue.length > 0) {
      void drain()
      return
    }
    setSpeaking(false)
  }

  return {
    speak: (text) => {
      queue.push(text)
      void drain()
    },
    prefetch: (text) => {
      if (prefetched.has(text)) return
      const pending = player.prepare(text)
      // Consumed lazily by drain; swallow here so a dropped prefetch never surfaces as an
      // unhandled rejection.
      pending.catch(() => undefined)
      prefetched.set(text, pending)
    },
    stop: () => {
      queue = []
      prefetched.clear()
      epoch += 1
      abort?.abort()
      abort = null
      processing = false
      setSpeaking(false)
    },
    speaking: () => isSpeaking,
  }
}
