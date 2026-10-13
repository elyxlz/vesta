package main

import (
	"slices"
	"testing"

	meowcaller "github.com/purpshell/meowcaller"
)

// tone is PCM for `frames` call frames of one constant level, so a test can tell from a frame
// which play it came from.
func tone(level float32, frames float64) []byte {
	samples := make([]float32, int(frames*meowcaller.FrameSamples))
	for i := range samples {
		samples[i] = level
	}
	return floatFrameToPCM16(samples)
}

// reportingSpeaker is a speaker whose playback reports land in the returned list, as
// "<state> <id>".
func reportingSpeaker() (*callSpeaker, *[]string) {
	reports := []string{}
	return &callSpeaker{report: func(id, state string) { reports = append(reports, state+" "+id) }}, &reports
}

func pull(t *testing.T, speaker *callSpeaker) []float32 {
	t.Helper()
	frame, err := speaker.ReadFrame()
	if err != nil {
		t.Fatalf("the speaker must give a frame on every pull, got %v", err)
	}
	if len(frame) != meowcaller.FrameSamples {
		t.Fatalf("frame length %d, want %d", len(frame), meowcaller.FrameSamples)
	}
	return frame
}

func assertLevel(t *testing.T, what string, got, want float32) {
	t.Helper()
	if diff := got - want; diff > 0.001 || diff < -0.001 {
		t.Fatalf("%s: level %v, want %v", what, got, want)
	}
}

func assertReports(t *testing.T, reports *[]string, want ...string) {
	t.Helper()
	if !slices.Equal(*reports, want) {
		t.Fatalf("playback reports %q, want %q", *reports, want)
	}
}

func TestSpeakerPlaysInArrivalOrderAndReportsEachPlay(t *testing.T) {
	speaker, reports := reportingSpeaker()
	speaker.begin("a")
	speaker.feed(tone(0.1, 1.5))
	speaker.end("a")
	speaker.begin("b")
	speaker.feed(tone(0.2, 1))
	speaker.end("b")
	assertReports(t, reports)

	assertLevel(t, "first frame of a", pull(t, speaker)[0], 0.1)
	assertReports(t, reports, "started a")

	// The last frame of a play is padded with silence.
	tail := pull(t, speaker)
	assertLevel(t, "tail of a", tail[0], 0.1)
	assertLevel(t, "padding after a", tail[len(tail)-1], 0)
	assertReports(t, reports, "started a")

	// `finished` goes out one pull after the last frame, and the next play starts.
	assertLevel(t, "frame of b", pull(t, speaker)[0], 0.2)
	assertReports(t, reports, "started a", "finished a", "started b")

	assertLevel(t, "silence after the queue", pull(t, speaker)[0], 0)
	assertReports(t, reports, "started a", "finished a", "started b", "finished b")
}

func TestSpeakerStartsAPlayWhileItsAudioStillArrives(t *testing.T) {
	speaker, reports := reportingSpeaker()
	speaker.begin("a")
	speaker.feed(tone(0.1, 1))

	assertLevel(t, "first frame", pull(t, speaker)[0], 0.1)
	assertReports(t, reports, "started a")

	// The play is not over: the call gets silence until more of it arrives.
	assertLevel(t, "wait for more audio", pull(t, speaker)[0], 0)
	assertReports(t, reports, "started a")

	speaker.feed(tone(0.1, 1))
	assertLevel(t, "second frame", pull(t, speaker)[0], 0.1)
	speaker.end("a")
	pull(t, speaker)
	assertReports(t, reports, "started a", "finished a")
}

func TestSpeakerJoinsASampleThatAChunkBoundarySplits(t *testing.T) {
	speaker, _ := reportingSpeaker()
	audio := tone(0.5, 1)
	speaker.begin("a")
	if speaker.feed(audio[:1]) {
		t.Fatal("half a sample is no audio yet")
	}
	if !speaker.feed(audio[1:]) {
		t.Fatal("the play has audio once whole samples arrived")
	}
	speaker.end("a")

	frame := pull(t, speaker)
	assertLevel(t, "first sample", frame[0], 0.5)
	assertLevel(t, "last sample", frame[len(frame)-1], 0.5)
}

func TestSpeakerPauseGivesSilenceAndKeepsThePosition(t *testing.T) {
	speaker, reports := reportingSpeaker()
	speaker.begin("a")
	speaker.feed(append(tone(0.1, 1), tone(0.2, 1)...))
	speaker.end("a")
	assertLevel(t, "before the pause", pull(t, speaker)[0], 0.1)

	speaker.pause()
	assertLevel(t, "paused", pull(t, speaker)[0], 0)
	assertLevel(t, "still paused", pull(t, speaker)[0], 0)
	assertReports(t, reports, "started a")

	speaker.resume()
	assertLevel(t, "after the pause", pull(t, speaker)[0], 0.2)
	pull(t, speaker)
	assertReports(t, reports, "started a", "finished a")
}

func TestSpeakerStopDiscardsTheQueueAndBufferedAudio(t *testing.T) {
	speaker, reports := reportingSpeaker()
	speaker.begin("a")
	speaker.feed(tone(0.1, 3))
	speaker.end("a")
	speaker.begin("b")
	speaker.feed(tone(0.2, 1))
	assertLevel(t, "a plays", pull(t, speaker)[0], 0.1)

	speaker.stop()
	if speaker.feed(tone(0.2, 1)) {
		t.Fatal("audio that arrives after a stop belongs to no play")
	}
	assertLevel(t, "after the stop", pull(t, speaker)[0], 0)

	// The queue is empty, so the next play starts at once and no stopped play is reported.
	speaker.begin("c")
	speaker.feed(tone(0.3, 1))
	assertLevel(t, "c plays", pull(t, speaker)[0], 0.3)
	assertReports(t, reports, "started a", "started c")
}

func TestSpeakerStopEndsAPause(t *testing.T) {
	speaker, _ := reportingSpeaker()
	speaker.begin("a")
	speaker.feed(tone(0.1, 2))
	pull(t, speaker)
	speaker.pause()
	speaker.stop()

	speaker.begin("b")
	speaker.feed(tone(0.2, 1))
	assertLevel(t, "b plays after the stop", pull(t, speaker)[0], 0.2)
}

func TestSpeakerReportsAPlayWithNoAudioAsFailed(t *testing.T) {
	speaker, reports := reportingSpeaker()
	speaker.begin("a")
	if !speaker.end("a") {
		t.Fatal("a play that ended with no audio must be reported as empty")
	}
	assertReports(t, reports, "failed a")

	assertLevel(t, "nothing plays", pull(t, speaker)[0], 0)
	assertReports(t, reports, "failed a")
}
