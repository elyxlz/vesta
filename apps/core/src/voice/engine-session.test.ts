import { describe, expect, it, vi } from "vitest";

import {
  MAX_PENDING_AUDIO_BYTES,
  createEngineSession,
  type EngineSessionCallbacks,
} from "./engine-session";
import { FakeEngineSocket, fakeCapture, fakeSpeaker } from "./voice-fakes";

function recorder() {
  const events: string[] = [];
  const errors: string[] = [];
  const active: boolean[] = [];
  const callbacks: EngineSessionCallbacks = {
    onTranscript: (text) => events.push(`transcript:${text}`),
    onTurnStart: () => events.push("turn_start"),
    onTurnEnd: (text) => events.push(`turn_end:${text}`),
    onTurnDropped: () => events.push("turn_dropped"),
    onSpeakingChange: (speaking) => events.push(`speaking:${String(speaking)}`),
    onPlayFailed: (message) => events.push(`play_failed:${message}`),
    onError: (message) => errors.push(message),
    onActiveChange: (value) => active.push(value),
  };
  return { events, errors, active, callbacks };
}

function setup(bargeIn = true) {
  const socket = new FakeEngineSocket();
  const cap = fakeCapture();
  const out = fakeSpeaker();
  const rec = recorder();
  const session = createEngineSession(
    {
      buildUrl: () => Promise.resolve("wss://x"),
      createSocket: () => socket,
      capture: cap.capture,
      speaker: out.speaker,
      playUrl: (path) => Promise.resolve(`https://host${path}`),
      client: "test",
    },
    rec.callbacks,
    { bargeIn },
  );
  // Start the session up to the point where the socket is dialed.
  const dial = async () => {
    const starting = session.start();
    await tick();
    return starting;
  };
  const started = async () => {
    const starting = dial();
    await tick();
    socket.accept();
    await starting;
  };
  return { socket, cap, out, session, dial, started, ...rec };
}

const tick = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

describe("the engine session", () => {
  it("sends start_session first, then the audio captured before the socket opened", async () => {
    const { socket, cap, session } = setup(false);
    const starting = session.start();
    await tick();
    cap.send(10);
    cap.send(20);
    expect(socket.sent).toHaveLength(0);
    socket.accept();
    await starting;

    expect(socket.frames()[0]).toEqual({
      type: "start_session",
      client: "test",
      audio: { encoding: "pcm_s16le", sample_rate: 16000, channels: 1 },
      playback: { delivery: "url", formats: ["mp3_22050"] },
      barge_in: false,
    });
    expect(typeof socket.sent[0]).toBe("string");
    expect(socket.audio().map((f) => f.byteLength)).toEqual([10, 20]);
    cap.send(5);
    expect(socket.audio()).toHaveLength(3);
  });

  it("keeps only the newest frames up to the pending cap", async () => {
    const { socket, cap, session } = setup();
    const starting = session.start();
    await tick();
    const half = MAX_PENDING_AUDIO_BYTES / 2;
    cap.send(half);
    cap.send(half);
    cap.send(2);
    socket.accept();
    await starting;
    expect(socket.audio().map((f) => f.byteLength)).toEqual([half, 2]);
  });

  it("is active only once the engine accepted the session", async () => {
    const { socket, session, active } = setup();
    const starting = session.start();
    await tick();
    socket.onopen?.();
    await tick();
    expect(session.active()).toBe(false);
    socket.emit({ type: "state", value: "listening" });
    await starting;
    expect(session.active()).toBe(true);
    expect(active).toEqual([true]);
  });

  it("refuses the start with the reason the engine gave", async () => {
    const { socket, session, active } = setup();
    const starting = session.start();
    await tick();
    socket.onopen?.();
    socket.emit({ type: "ended", reason: "not_configured" });

    await expect(starting).rejects.toThrow(
      "Speech-to-text is off or not set up",
    );
    expect(session.active()).toBe(false);
    expect(active).toEqual([]);
    expect(socket.closed).toBe(true);
  });

  it("stays inactive when the engine ends the session while the microphone still comes up", async () => {
    const socket = new FakeEngineSocket();
    let micReady: () => void = () => undefined;
    const rec = recorder();
    const session = createEngineSession(
      {
        buildUrl: () => Promise.resolve("wss://x"),
        createSocket: () => socket,
        capture: {
          start: () =>
            new Promise<void>((resolve) => {
              micReady = resolve;
            }),
          stop: () => undefined,
        },
        speaker: fakeSpeaker().speaker,
        playUrl: (path) => Promise.resolve(path),
        client: "test",
      },
      rec.callbacks,
      { bargeIn: true },
    );
    const starting = session.start();
    await tick();
    socket.accept();
    socket.emit({ type: "ended", reason: "stt_failed" });
    micReady();
    await starting;

    expect(session.active()).toBe(false);
    expect(rec.active).toEqual([]);
    expect(rec.errors).toEqual(["The transcription service failed"]);
  });

  it("refuses the start when the socket closes before the engine answers", async () => {
    const { socket, session } = setup();
    const starting = session.start();
    await tick();
    socket.onclose?.("");
    await expect(starting).rejects.toThrow("Could not connect to live voice");
  });

  it("delivers a turn: its live text, its start, the end of its live text, then its end", async () => {
    const { socket, events, started } = setup();
    await started();
    socket.emit({ type: "transcript", text: "what is" });
    socket.emit({ type: "turn_start" });
    socket.emit({ type: "transcript", text: "what is the weather" });
    socket.emit({ type: "transcript", text: "" });
    socket.emit({ type: "turn_end", text: "What is the weather?" });

    expect(events).toEqual([
      "transcript:what is",
      "turn_start",
      "transcript:what is the weather",
      "transcript:",
      "turn_end:What is the weather?",
    ]);
  });

  it("delivers a dropped turn, and does nothing for text that was ignored", async () => {
    const { socket, events, started } = setup();
    await started();
    socket.emit({ type: "transcript", text: "uh" });
    socket.emit({ type: "transcript", text: "" });
    socket.emit({ type: "turn_dropped", text: "", kind: null });
    socket.emit({ type: "transcript", text: "mhm" });
    socket.emit({ type: "transcript", text: "" });
    socket.emit({ type: "ignored", text: "mhm", kind: "backchannel" });

    expect(events).toEqual([
      "transcript:uh",
      "transcript:",
      "turn_dropped",
      "transcript:mhm",
      "transcript:",
    ]);
  });

  it("ignores a frame type that it does not know", async () => {
    const { socket, events, errors, started } = setup();
    await started();
    socket.emit({ type: "a_new_frame", text: "x" });
    socket.onmessage?.("not json");
    expect(events).toEqual([]);
    expect(errors).toEqual([]);
  });

  it("reports a reply the engine could not say and keeps the session", async () => {
    const { socket, session, events, errors, started } = setup();
    await started();
    socket.emit({ type: "error", id: "reply-1", message: "tts is off" });
    expect(events).toEqual(["play_failed:tts is off"]);
    expect(errors).toEqual([]);
    expect(session.active()).toBe(true);
  });

  it("tells the user once about a reply that the engine and the speaker both report", async () => {
    const { socket, out, events, started } = setup();
    await started();
    const failures = () => events.filter((e) => e.startsWith("play_failed"));
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/t1" });
    socket.emit({ type: "play", id: "reply-2", url: "/voice/play/t2" });
    // The engine reports the first reply before the speaker does.
    socket.emit({ type: "error", id: "reply-1", message: "synthesis failed" });
    await vi.waitFor(() => {
      expect(out.plays).toHaveLength(1);
    });
    out.plays[0]?.fail();
    await vi.waitFor(() => {
      expect(out.plays).toHaveLength(2);
    });
    // The speaker reports the second reply before the engine does.
    out.plays[1]?.fail();
    await vi.waitFor(() => {
      expect(failures()).toHaveLength(2);
    });
    socket.emit({ type: "error", id: "reply-2", message: "synthesis failed" });

    expect(failures()).toEqual([
      "play_failed:synthesis failed",
      "play_failed:Voice playback failed",
    ]);
  });

  it("asks the engine to speak, and holds a reply asked for during the start", async () => {
    const { socket, session, dial } = setup();
    const starting = dial();
    await tick();
    session.speak("early");
    socket.accept();
    await starting;
    session.speak("later");

    expect(socket.frames().slice(1)).toEqual([
      { type: "speak", id: "reply-1", text: "early" },
      { type: "speak", id: "reply-2", text: "later" },
    ]);
  });

  it("plays what the engine sends and reports the speaker to it", async () => {
    const { socket, out, events, started } = setup();
    await started();
    socket.emit({
      type: "play",
      id: "reply-1",
      format: "mp3_22050",
      url: "/voice/play/tok",
    });
    await vi.waitFor(() => {
      expect(out.urls()).toEqual(["https://host/voice/play/tok"]);
    });
    out.plays[0]?.started();
    out.plays[0]?.finish();
    await vi.waitFor(() => {
      expect(events).toEqual(["speaking:true", "speaking:false"]);
    });

    expect(socket.frames().slice(1)).toEqual([
      { type: "playback", id: "reply-1", state: "started" },
      { type: "playback", id: "reply-1", state: "finished" },
    ]);
  });

  it("pauses, resumes, and stops the speaker when the engine says so", async () => {
    const { socket, session, out, started } = setup();
    await started();
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/tok" });
    await vi.waitFor(() => {
      expect(out.plays).toHaveLength(1);
    });
    socket.emit({ type: "pause_playback" });
    socket.emit({ type: "resume_playback" });
    expect(out.calls).toEqual(["pause", "resume"]);

    socket.emit({ type: "stop_playback", id: "reply-1", dropped: [] });
    expect(session.speaking()).toBe(false);
    // The engine stopped the play itself, so no report goes back.
    expect(socket.frames().slice(1)).toEqual([]);
  });

  it("tells the engine when the user stops the speech on the device", async () => {
    const { socket, session, started } = setup();
    await started();
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/tok" });
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true);
    });
    session.stopSpeech();

    expect(session.speaking()).toBe(false);
    expect(socket.frames().at(-1)).toEqual({
      type: "playback",
      state: "stopped_by_user",
    });
  });

  it("reports the reason and goes inactive when the engine ends the session", async () => {
    const { socket, session, errors, active, started } = setup();
    await started();
    socket.emit({ type: "ended", reason: "stt_failed" });

    expect(errors).toEqual(["The transcription service failed"]);
    expect(active).toEqual([true, false]);
    expect(session.active()).toBe(false);
  });

  it("reports a socket that closes with no ended frame", async () => {
    const { socket, errors, active, started } = setup();
    await started();
    socket.onclose?.("");
    expect(errors).toEqual(["Voice connection closed unexpectedly"]);
    expect(active).toEqual([true, false]);
  });

  it("ends the session on stop: end_session, then the socket and the speaker", async () => {
    const { socket, session, active, started } = setup();
    await started();
    socket.emit({ type: "play", id: "reply-1", url: "/voice/play/tok" });
    await vi.waitFor(() => {
      expect(session.speaking()).toBe(true);
    });
    session.stop();

    expect(socket.frames().at(-1)).toEqual({ type: "end_session" });
    expect(socket.closed).toBe(true);
    expect(session.speaking()).toBe(false);
    expect(active).toEqual([true, false]);
  });

  it("abandons a start the caller stopped before the engine answered", async () => {
    const { session, errors, active, dial } = setup();
    const starting = dial();
    await tick();
    session.stop();
    await starting;
    expect(session.active()).toBe(false);
    expect(errors).toEqual([]);
    expect(active).toEqual([]);
  });
});
