package main

import (
	"encoding/binary"
	"io"

	meowcaller "github.com/purpshell/meowcaller"
)

// The call bridge speaks two PCM representations of the same 16 kHz mono audio: meowcaller's
// decoded float32 frames (what the peer's voice arrives as, and what we play back) and the
// signed 16-bit little-endian bytes both Deepgram STT and ElevenLabs `pcm_16000` TTS use on the
// wire. These helpers convert between them; the voice backend and meowcaller agree on 16 kHz mono
// (meowcaller.SampleRate), so there is no resampling here.

// floatFrameToPCM16 encodes a float32 frame in [-1, 1] as signed 16-bit little-endian bytes,
// clamping out-of-range samples so a hot frame cannot wrap around into noise.
func floatFrameToPCM16(frame []float32) []byte {
	out := make([]byte, len(frame)*2)
	for i, s := range frame {
		if s > 1 {
			s = 1
		} else if s < -1 {
			s = -1
		}
		binary.LittleEndian.PutUint16(out[i*2:], uint16(int16(s*32767)))
	}
	return out
}

// pcm16ToFloat decodes signed 16-bit little-endian PCM bytes into float32 samples in [-1, 1]. A
// trailing odd byte (a truncated sample) is dropped.
func pcm16ToFloat(b []byte) []float32 {
	n := len(b) / 2
	out := make([]float32, n)
	for i := 0; i < n; i++ {
		out[i] = float32(int16(binary.LittleEndian.Uint16(b[i*2:]))) / 32768
	}
	return out
}

// pcmSource plays a fixed buffer of 16 kHz mono float32 samples into a call as one meowcaller
// AudioSource: each ReadFrame hands back the next FrameSamples-long frame (the final partial frame
// zero-padded), then io.EOF, at which point meowcaller's Player goes idle and the call sends
// silence. One pcmSource backs one `whatsapp say` utterance; the next utterance is a fresh source.
type pcmSource struct {
	samples []float32
	pos     int
}

func newPCMSource(samples []float32) *pcmSource {
	return &pcmSource{samples: samples}
}

func (p *pcmSource) ReadFrame() ([]float32, error) {
	if p.pos >= len(p.samples) {
		return nil, io.EOF
	}
	frame := make([]float32, meowcaller.FrameSamples)
	n := copy(frame, p.samples[p.pos:])
	p.pos += n
	return frame, nil
}

func (p *pcmSource) Close() error {
	p.pos = len(p.samples)
	return nil
}
