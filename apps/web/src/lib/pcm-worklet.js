// AudioWorklet processor — runs on the audio rendering thread.
// Captures Float32 PCM samples from the input and posts them to the main thread.
class PCMProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0];
    if (input.length === 0) return true;
    const channel = input[0];
    if (!channel || channel.length === 0) return true;
    const copy = new Float32Array(channel);
    this.port.postMessage(copy, [copy.buffer]);
    return true;
  }
}
registerProcessor("pcm-processor", PCMProcessor);
