package main

import (
	"bytes"
	"sync"

	meowcaller "github.com/purpshell/meowcaller"
)

// What the call did with a play, in the words of the voice engine's `playback` frame.
const (
	playbackStarted  = "started"
	playbackFinished = "finished"
	playbackFailed   = "failed"
)

// callSpeaker is the one meowcaller AudioSource of a call: the queue of the plays the voice
// engine sent, played in arrival order. The call's send loop pulls one frame every 60 ms through
// ReadFrame for the whole call, and the socket reader feeds each play while its audio arrives,
// so a play starts at its first full frame. A pull with nothing to play gives silence, and so
// does every pull while paused, which keeps the position. report gets each playback report in
// order; it runs on the send loop and must not block.
type callSpeaker struct {
	mu     sync.Mutex
	queue  []*speakerPlay
	paused bool
	// tail is the play whose last frame went to the call on the previous pull.
	tail   string
	report func(id, state string)
}

type speakerPlay struct {
	id string
	// pending holds the samples that the call did not get yet.
	pending []float32
	// half is the first byte of a sample that the end of a chunk split.
	half    []byte
	heard   bool // at least one sample arrived
	started bool // its first frame went to the call
	done    bool // every byte of the play arrived
}

// begin adds a play to the end of the queue. The audio that arrives next belongs to it.
func (s *callSpeaker) begin(id string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.queue = append(s.queue, &speakerPlay{id: id})
}

// feed adds signed 16-bit little-endian PCM to the play that still receives audio, and says if
// that play has audio. Bytes that belong to no play are discarded.
func (s *callSpeaker) feed(pcm []byte) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.queue) == 0 || s.queue[len(s.queue)-1].done {
		return false
	}
	play := s.queue[len(s.queue)-1]
	if len(play.half) > 0 {
		pcm = append(play.half, pcm...)
	}
	whole := len(pcm) &^ 1
	play.pending = append(play.pending, pcm16ToFloat(pcm[:whole])...)
	play.half = bytes.Clone(pcm[whole:])
	play.heard = play.heard || whole > 0
	return play.heard
}

// end marks that every byte of a play arrived. A play that got no audio cannot play: it leaves
// the queue with a `failed` report, and end returns true.
func (s *callSpeaker) end(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	for i, play := range s.queue {
		if play.id != id || play.done {
			continue
		}
		play.done = true
		if play.heard {
			return false
		}
		s.queue = append(s.queue[:i], s.queue[i+1:]...)
		s.report(id, playbackFailed)
		return true
	}
	return false
}

func (s *callSpeaker) pause() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.paused = true
}

func (s *callSpeaker) resume() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.paused = false
}

// stop ends the audio at once and discards every queued play with its buffered audio. It sends
// no report: the engine that asked for the stop already knows which plays are gone.
func (s *callSpeaker) stop() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.queue = nil
	s.tail = ""
	s.paused = false
}

// ReadFrame gives the call its next 60 ms. `started` goes out with the first frame of a play.
// `finished` goes out one pull after its last frame, when that frame has played. The last
// frame of a play is padded with silence, so the next play starts on a frame of its own.
func (s *callSpeaker) ReadFrame() ([]float32, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	frame := make([]float32, meowcaller.FrameSamples)
	if s.tail != "" {
		s.report(s.tail, playbackFinished)
		s.tail = ""
	}
	if s.paused {
		return frame, nil
	}
	for len(s.queue) > 0 {
		play := s.queue[0]
		if len(play.pending) >= len(frame) || (play.done && len(play.pending) > 0) {
			play.pending = play.pending[copy(frame, play.pending):]
			if !play.started {
				play.started = true
				s.report(play.id, playbackStarted)
			}
			if play.done && len(play.pending) == 0 {
				s.tail = play.id
				s.queue = s.queue[1:]
			}
			return frame, nil
		}
		if !play.done {
			// More audio of this play is on its way.
			break
		}
		// Its last frame went out on an earlier pull, before the end of the play was known.
		s.report(play.id, playbackFinished)
		s.queue = s.queue[1:]
	}
	return frame, nil
}

func (s *callSpeaker) Close() error {
	s.stop()
	return nil
}
