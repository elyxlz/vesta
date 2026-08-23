import { describe, expect, it } from "vitest"

import { createTtsQueue, type SpeechPlayer } from "./tts-queue"

interface PlayCall {
  id: string
  signal: AbortSignal
  finish: () => void
  fail: () => void
}

function fakePlayer(): {
  player: SpeechPlayer
  prepares: string[]
  plays: PlayCall[]
} {
  const prepares: string[] = []
  const plays: PlayCall[] = []
  const player: SpeechPlayer = {
    prepare: (text) => {
      prepares.push(text)
      return Promise.resolve(`id:${text}`)
    },
    play: (id, signal) =>
      new Promise<void>((resolve, reject) => {
        signal.addEventListener("abort", () => {
          resolve()
        })
        plays.push({
          id,
          signal,
          finish: () => {
            resolve()
          },
          fail: () => {
            reject(new Error("playback failed"))
          },
        })
      }),
  }
  return { player, prepares, plays }
}

const tick = (): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, 0)
  })

describe("createTtsQueue", () => {
  it("prepares and plays a spoken text", async () => {
    const { player, prepares, plays } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.speak("hello")
    await tick()

    expect(prepares).toEqual(["hello"])
    expect(plays.map((p) => p.id)).toEqual(["id:hello"])
    expect(queue.speaking()).toBe(true)
  })

  it("plays queued texts in order without overlap", async () => {
    const { player, plays } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.speak("first")
    queue.speak("second")
    await tick()

    expect(plays.map((p) => p.id)).toEqual(["id:first"])
    plays[0]?.finish()
    await tick()
    expect(plays.map((p) => p.id)).toEqual(["id:first", "id:second"])
  })

  it("reports speaking transitions across a drain", async () => {
    const { player, plays } = fakePlayer()
    const transitions: boolean[] = []
    const queue = createTtsQueue(player, {
      onSpeakingChange: (speaking) => transitions.push(speaking),
    })

    queue.speak("hello")
    await tick()
    plays[0]?.finish()
    await tick()

    expect(transitions).toEqual([true, false])
    expect(queue.speaking()).toBe(false)
  })

  it("stop aborts the current playback and drops the queue", async () => {
    const { player, plays } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.speak("first")
    queue.speak("second")
    await tick()
    queue.stop()
    await tick()

    expect(plays[0]?.signal.aborted).toBe(true)
    expect(plays.map((p) => p.id)).toEqual(["id:first"])
    expect(queue.speaking()).toBe(false)
  })

  it("speaks again after a stop", async () => {
    const { player, plays } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.speak("first")
    await tick()
    queue.stop()
    queue.speak("third")
    await tick()

    expect(plays.map((p) => p.id)).toEqual(["id:first", "id:third"])
  })

  it("uses a prefetched preparation instead of preparing again", async () => {
    const { player, prepares, plays } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.prefetch("hello")
    await tick()
    queue.speak("hello")
    await tick()
    plays[0]?.finish()
    await tick()

    expect(prepares).toEqual(["hello"])
  })

  it("falls back to preparing when the prefetch failed", async () => {
    const prepares: string[] = []
    let played = ""
    const player: SpeechPlayer = {
      prepare: (text) => {
        prepares.push(text)
        return prepares.length === 1
          ? Promise.reject(new Error("prefetch failed"))
          : Promise.resolve("fresh-id")
      },
      play: (id) => {
        played = id
        return Promise.resolve()
      },
    }
    const queue = createTtsQueue(player, {})

    queue.prefetch("hello")
    await tick()
    queue.speak("hello")
    await tick()

    expect(prepares).toEqual(["hello", "hello"])
    expect(played).toBe("fresh-id")
  })

  it("reports a failed playback and continues with the next text", async () => {
    const { player, plays } = fakePlayer()
    const errors: string[] = []
    const queue = createTtsQueue(player, {
      onError: (message) => errors.push(message),
    })

    queue.speak("first")
    queue.speak("second")
    await tick()
    plays[0]?.fail()
    await tick()

    expect(errors).toEqual(["Voice playback failed"])
    expect(plays.map((p) => p.id)).toEqual(["id:first", "id:second"])
  })

  it("stop clears prefetched texts", async () => {
    const { player, prepares } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.prefetch("hello")
    await tick()
    queue.stop()
    queue.speak("hello")
    await tick()

    expect(prepares).toEqual(["hello", "hello"])
  })

  it("prefetch is a no-op for an already prefetched text", async () => {
    const { player, prepares } = fakePlayer()
    const queue = createTtsQueue(player, {})

    queue.prefetch("hello")
    queue.prefetch("hello")
    await tick()

    expect(prepares).toEqual(["hello"])
  })
})
