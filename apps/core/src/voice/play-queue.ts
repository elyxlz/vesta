// The plays of one engine session, in arrival order over an injected speaker. The engine paces
// nothing: it sends each play as soon as it can, and it says when to pause, resume, or stop.
// Each report says what the speaker did, which is the only way the engine knows that the agent
// is speaking, so a report is sent at the moment the speaker does the thing.

export interface Speaker {
  // Plays the audio at `url`. `onStarted` fires when the first sound reaches the speaker.
  // Resolves when the audio ended or the signal aborted; rejects when it cannot play.
  play: (
    url: string,
    signal: AbortSignal,
    onStarted: () => void,
  ) => Promise<void>;
  // Pause and continue the audio that plays now. Both do nothing when none plays.
  pause: () => void;
  resume: () => void;
}

export type PlayReport = "started" | "finished" | "failed";

// A play whose sound does not start within this time is given up as failed, so one stream
// that never loads cannot hold every play after it.
export const PLAY_START_TIMEOUT_MS = 15_000;

export interface PlayQueueDeps {
  speaker: Speaker;
  // The url a speaker can fetch for the path the engine named.
  resolveUrl: (path: string) => Promise<string>;
  report: (id: string, state: PlayReport) => void;
  onSpeakingChange: (speaking: boolean) => void;
  // The speaker could not play this play, after its `failed` report.
  onFailed: (id: string) => void;
}

export interface PlayQueue {
  enqueue: (id: string, path: string) => void;
  pause: () => void;
  resume: () => void;
  // Stops the audio and drops every queued play. It reports nothing: a stop comes from the
  // engine or is told to it by the caller.
  stop: () => void;
  speaking: () => boolean;
}

export function createPlayQueue(deps: PlayQueueDeps): PlayQueue {
  let queue: { id: string; path: string }[] = [];
  // True while a drain loop runs, which is the time the queue counts as speaking.
  let draining = false;
  let abort: AbortController | null = null;
  // Bumped by stop to end an in-flight drain loop, so a stop followed by a new play never
  // leaves two loops on the speaker.
  let epoch = 0;
  // The engine pauses and resumes the whole queue, also in the gap between two plays: a
  // play that is not on the speaker yet waits for the resume.
  let paused = false;
  let onResume: (() => void) | null = null;
  // True while a play is on the speaker, the only time a pause or a resume reaches it.
  let sounding = false;

  const resumed = (): Promise<void> =>
    paused
      ? new Promise((resolve) => {
          onResume = resolve;
        })
      : Promise.resolve();

  const setDraining = (value: boolean): void => {
    if (draining === value) return;
    draining = value;
    deps.onSpeakingChange(value);
  };

  const playOne = async (
    play: { id: string; path: string },
    myEpoch: number,
  ): Promise<void> => {
    const controller = new AbortController();
    abort = controller;
    // What became of this play, set from the speaker's callback and from the watchdog.
    const outcome = { started: false, gaveUp: false };
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    try {
      const url = await deps.resolveUrl(play.path);
      await resumed();
      if (epoch !== myEpoch) return;
      watchdog = setTimeout(() => {
        if (outcome.started) return;
        outcome.gaveUp = true;
        controller.abort();
      }, PLAY_START_TIMEOUT_MS);
      sounding = true;
      await deps.speaker.play(url, controller.signal, () => {
        outcome.started = true;
        if (!controller.signal.aborted) deps.report(play.id, "started");
      });
      if (outcome.gaveUp) throw new Error("the audio did not start");
      if (!controller.signal.aborted) deps.report(play.id, "finished");
    } catch {
      if (controller.signal.aborted && !outcome.gaveUp) return;
      deps.report(play.id, "failed");
      deps.onFailed(play.id);
    } finally {
      if (watchdog !== null) clearTimeout(watchdog);
      if (abort === controller) {
        abort = null;
        sounding = false;
      }
    }
  };

  const drain = async (): Promise<void> => {
    if (draining) return;
    setDraining(true);
    const myEpoch = epoch;
    // The epoch is checked before each shift, so a loop that a stop ended takes no play of
    // the loop after it.
    while (epoch === myEpoch) {
      const play = queue.shift();
      if (!play) break;
      await playOne(play, myEpoch);
    }
    // A stop took the queue over and already reset the flags.
    if (epoch !== myEpoch) return;
    setDraining(false);
  };

  return {
    enqueue: (id, path) => {
      queue.push({ id, path });
      void drain();
    },
    pause: () => {
      paused = true;
      if (sounding) deps.speaker.pause();
    },
    resume: () => {
      paused = false;
      onResume?.();
      onResume = null;
      if (sounding) deps.speaker.resume();
    },
    stop: () => {
      queue = [];
      epoch += 1;
      abort?.abort();
      abort = null;
      sounding = false;
      // A stop ends a pause too: the play that waited for the resume wakes and leaves.
      paused = false;
      onResume?.();
      onResume = null;
      setDraining(false);
    },
    speaking: () => draining,
  };
}
