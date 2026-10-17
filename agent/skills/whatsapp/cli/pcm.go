package main

import "encoding/binary"

// The call bridge speaks two PCM representations of the same 16 kHz mono audio: meowcaller's
// float32 frames (what the peer's voice arrives as, and what the call plays) and the signed
// 16-bit little-endian bytes of the voice engine socket (the peer's audio on the way up, and
// the `pcm_16000` plays on the way down). These helpers convert between them. Both sides use
// 16 kHz mono (meowcaller.SampleRate), so there is no resampling here.

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
