import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createVoiceSession,
  type VoiceMode,
  type VoiceSessionCallbacks,
} from "./voice-session";
import type { AudioCapture } from "./engine-session";
import { FakeEngineSocket, fakeCapture, fakeSpeaker } from "./voice-fakes";

function recorder() {
  const events = {
    transcripts: [] as string[],
    sends: [] as string[],
    errors: [] as string[],
    modes: [] as (VoiceMode | null)[],
    listening: [] as boolean[],
    speaking: [] as boolean[],
    userSpeaking: [] as boolean[],
    wakeWaiting: [] as boolean[],
    inactivity: 0,
  };
  const callbacks: VoiceSessionCallbacks = {
    onTranscript: (t) => events.transcripts.push(t),
    onSend: (t) => events.sends.push(t),
    onError: (m) => events.errors.push(m),
    onModeChange: (m) => events.modes.push(m),
    onListeningChange: (l) => events.listening.push(l),
    onSpeakingChange: (s) => events.speaking.push(s),
    onUserSpeakingChange: (s) => events.userSpeaking.push(s),
    onWakeWaitingChange: (w) => events.wakeWaiting.push(w),
    onInactivityStop: () => (events.inactivity += 1),
  };
  return { events, callbacks };
}

function setup(capture: AudioCapture = fakeCapture().capture) {
  // Each session dials a socket of its own.
  const sockets: FakeEngineSocket[] = [];
  const out = fakeSpeaker();
  const prepared: string[] = [];
  const { events, callbacks } = recorder();
  const session = createVoiceSession(
    {
      buildUrl: () => Promise.resolve("wss://x"),
      createSocket: () => {
        const socket = new FakeEngineSocket();
        sockets.push(socket);
        return socket;
      },
      capture,
      speaker: out.speaker,
      playUrl: (path) => Promise.resolve(`https://host${path}`),
      prepareSpeech: (text) => {
        prepared.push(text);
        return Promise.resolve(`https://host/stream/${text}`);
      },
      client: "test",
    },
    callbacks,
    () => ({ inactivityMs: 1000 }),
  );
  const startAnd = async (mode: VoiceMode): Promise<FakeEngineSocket> => {
    const p = session.start(mode);
    await vi.advanceTimersByTimeAsync(0);
    const socket = sockets.at(-1);
    if (!socket) throw new Error("no socket was dialed");
    socket.accept();
    await p;
    return socket;
  };
  const turn = (socket: FakeEngineSocket, text: string): void => {
    socket.emit({ type: "turn_start" });
    socket.emit({ type: "transcript", text: "" });
    socket.emit({ type: "turn_end", text });
  };
  const fireTimers = () => {
    vi.runOnlyPendingTimers();
  };
  return { session, events, out, prepared, startAnd, turn, fireTimers };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the voice session", () => {
  it("leaves the microphone off when the user stops while it starts", async () => {
    let on = false;
    let open: () => void = () => undefined;
    const { session } = setup({
      start: () =>
        new Promise((resolve) => {
          open = () => {
            on = true;
            resolve();
          };
        }),
      stop: () => {
        on = false;
      },
    });

    const started = session.start("conversation");
    await vi.advanceTimersByTimeAsync(0);
    session.stop();
    // The user grants the microphone after the stop has settled.
    await vi.advanceTimersByTimeAsync(0);
    open();
    await started;

    expect(on).toBe(false);
  });

  it("marks the mode before the microphone opens and clears it on stop", async () => {
    const { session, events } = setup();
    const p = session.start("dictation");
    expect(events.modes).toEqual(["dictation"]);
    expect(session.mode()).toBe("dictation");
    session.stop();
    await p;
    expect(events.modes).toEqual(["dictation", null]);
  });

  it("a conversation can stop a reply by voice and dictation cannot", async () => {
    const { session, startAnd } = setup();
    const dictation = await startAnd("dictation");
    expect(dictation.frames()[0]?.barge_in).toBe(false);
    session.cancel();
    const conversation = await startAnd("conversation");
    expect(conversation.frames()[0]?.barge_in).toBe(true);
  });

  it("dictation listens with no wake word and a conversation follows the wake word behavior", async () => {
    const { session, startAnd } = setup();
    const dictation = await startAnd("dictation");
    expect(dictation.frames()[0]?.wake_word).toBe(false);
    session.cancel();
    const conversation = await startAnd("conversation");
    expect(conversation.frames()[0]?.wake_word).toBe(true);
  });

  it("dictation accumulates turns and sends one message on confirm", async () => {
    const { session, events, startAnd, turn } = setup();
    const socket = await startAnd("dictation");
    turn(socket, "buy milk");
    socket.emit({ type: "transcript", text: "and eggs" });
    expect(events.transcripts.at(-1)).toBe("buy milk and eggs");
    expect(events.sends).toEqual([]);
    session.stop();
    expect(events.sends).toEqual(["buy milk and eggs"]);
  });

  it("dictation leaves out live text that the engine dropped", async () => {
    const { session, events, startAnd, turn } = setup();
    const socket = await startAnd("dictation");
    turn(socket, "buy milk");
    socket.emit({ type: "transcript", text: "uh" });
    socket.emit({ type: "transcript", text: "" });
    socket.emit({ type: "turn_dropped", text: "", kind: null });
    expect(events.transcripts.at(-1)).toBe("buy milk");
    session.stop();
    expect(events.sends).toEqual(["buy milk"]);
  });

  it("dictation cancel sends nothing", async () => {
    const { session, events, startAnd, turn } = setup();
    const socket = await startAnd("dictation");
    turn(socket, "never mind");
    session.cancel();
    expect(events.sends).toEqual([]);
    expect(session.mode()).toBeNull();
  });

  it("a conversation sends each turn as it ends and keeps listening", async () => {
    const { session, events, startAnd, turn } = setup();
    const socket = await startAnd("conversation");
    turn(socket, "first");
    turn(socket, "second");
    expect(events.sends).toEqual(["first", "second"]);
    expect(events.transcripts.at(-1)).toBe("");
    expect(session.mode()).toBe("conversation");
  });

  it("a conversation drops its turn in progress on stop", async () => {
    const { session, events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "transcript", text: "half a thought" });
    session.stop();
    expect(events.sends).toEqual([]);
  });

  it("a silent conversation ends itself and reports the inactivity stop", async () => {
    const { session, events, startAnd, turn, fireTimers } = setup();
    const socket = await startAnd("conversation");
    turn(socket, "last words");
    fireTimers();
    expect(session.mode()).toBeNull();
    expect(events.inactivity).toBe(1);
  });

  it("dictation arms no inactivity timer", async () => {
    const { session, events, startAnd, fireTimers } = setup();
    await startAnd("dictation");
    fireTimers();
    expect(session.mode()).toBe("dictation");
    expect(events.inactivity).toBe(0);
  });

  it("a conversation reports the user's turn and closes it on turn end", async () => {
    const { events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "turn_start" });
    expect(events.userSpeaking).toEqual([true]);
    socket.emit({ type: "turn_end", text: "hello" });
    expect(events.userSpeaking).toEqual([true, false]);
    expect(events.sends).toEqual(["hello"]);
  });

  it("a dropped turn closes the user's turn and sends nothing", async () => {
    const { events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "turn_start" });
    socket.emit({ type: "turn_dropped", text: "", kind: null });
    expect(events.userSpeaking).toEqual([true, false]);
    expect(events.sends).toEqual([]);
  });

  it("a conversation reports the wake gate until the session ends", async () => {
    const { session, events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "wake_listening", value: true });
    socket.emit({ type: "wake_listening", value: false });
    socket.emit({ type: "wake_listening", value: true });
    session.stop();
    expect(events.wakeWaiting).toEqual([true, false, true, false]);
  });

  it("a session that ends in the middle of a turn closes the user's turn", async () => {
    const { session, events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "turn_start" });
    session.cancel();
    expect(events.userSpeaking).toEqual([true, false]);
  });

  it("dictation never reports the user's turn", async () => {
    const { session, events, startAnd, turn } = setup();
    const socket = await startAnd("dictation");
    turn(socket, "noted");
    session.stop();
    expect(events.userSpeaking).toEqual([]);
  });

  it("during a session a reply goes to the engine, which decides when it plays", async () => {
    const { session, out, prepared, startAnd } = setup();
    const socket = await startAnd("conversation");
    session.speak("a reply");
    session.prefetch("a reply");

    expect(socket.frames().at(-1)).toEqual({
      type: "speak",
      id: "reply-1",
      text: "a reply",
    });
    expect(prepared).toEqual([]);
    expect(out.plays).toEqual([]);
  });

  it("outside a session a reply is read aloud through the streamed route", async () => {
    const { session, events, out, prepared } = setup();
    session.speak("a reply");
    await vi.waitFor(() => {
      expect(out.urls()).toEqual(["https://host/stream/a reply"]);
    });
    expect(prepared).toEqual(["a reply"]);
    expect(session.speaking()).toBe(true);
    out.plays[0]?.finish();
    await vi.waitFor(() => {
      expect(events.speaking).toEqual([true, false]);
    });
  });

  it("a new session takes the speaker from a reply that is read aloud", async () => {
    const { session, startAnd } = setup();
    session.speak("a reply");
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true);
    });
    await startAnd("conversation");
    expect(session.speaking()).toBe(false);
  });

  it("speaks one state for the engine's plays and the read-aloud queue", async () => {
    const { session, events, out, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/tok" });
    await vi.waitFor(() => {
      expect(out.urls()).toEqual(["https://host/voice/play/tok"]);
    });
    expect(session.speaking()).toBe(true);
    session.stopSpeech();
    expect(events.speaking).toEqual([true, false]);
  });

  it("a play that fails is reported and the session goes on", async () => {
    const { session, events, out, startAnd, turn } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/tok" });
    await vi.waitFor(() => {
      expect(out.plays).toHaveLength(1);
    });
    out.plays[0]?.fail();
    await vi.waitFor(() => {
      expect(events.errors).toEqual(["Voice playback failed"]);
    });

    expect(session.mode()).toBe("conversation");
    expect(session.listening()).toBe(true);
    turn(socket, "still here");
    expect(events.sends).toEqual(["still here"]);
    session.stop();
    expect(socket.frames().at(-1)).toEqual({ type: "end_session" });
  });

  it("reports listening once the engine accepted the session", async () => {
    const { session, events, startAnd } = setup();
    expect(session.listening()).toBe(false);
    await startAnd("conversation");
    expect(session.listening()).toBe(true);
    expect(events.listening).toContain(true);
  });

  it("an engine that ends the session reports the reason and clears the mode", async () => {
    const { session, events, startAnd } = setup();
    const socket = await startAnd("conversation");
    socket.emit({ type: "ended", reason: "stt_limit" });
    expect(events.errors).toEqual([
      "The speech provider is at its limit of sessions. Try again in a moment",
    ]);
    expect(session.mode()).toBeNull();
    expect(events.listening).toEqual([true, false]);
  });
});
