import { useSettings } from "@/stores/use-settings";

const ELEVENLABS_API_KEY = "sk_4364ff2714b290ea63ffe5a92fc28ffa0ca89161ec40ba05";
const MODEL_ID = "eleven_flash_v2_5";

export const VOICES: { id: string; name: string; preview: string }[] = [
  { id: "CwhRBWXzGAHq8TQ4Fs17", name: "Roger", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/CwhRBWXzGAHq8TQ4Fs17/58ee3ff5-f6f2-4628-93b8-e38eb31806b0.mp3" },
  { id: "EXAVITQu4vr4xnSDxMaL", name: "Sarah", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/EXAVITQu4vr4xnSDxMaL/01a3e33c-6e99-4ee7-8543-ff2216a32186.mp3" },
  { id: "FGY2WhTYpPnrIDTdsKH5", name: "Laura", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/FGY2WhTYpPnrIDTdsKH5/67341759-ad08-41a5-be6e-de12fe448618.mp3" },
  { id: "IKne3meq5aSn9XLyUdCD", name: "Charlie", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/IKne3meq5aSn9XLyUdCD/102de6f2-22ed-43e0-a1f1-111fa75c5481.mp3" },
  { id: "JBFqnCBsd6RMkjVDRZzb", name: "George", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/JBFqnCBsd6RMkjVDRZzb/e6206d1a-0721-4787-aafb-06a6e705cac5.mp3" },
  { id: "N2lVS1w4EtoT3dr4eOWO", name: "Callum", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/N2lVS1w4EtoT3dr4eOWO/ac833bd8-ffda-4938-9ebc-b0f99ca25481.mp3" },
  { id: "SAz9YHcvj6GT2YYXdXww", name: "River", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/SAz9YHcvj6GT2YYXdXww/e6c95f0b-2227-491a-b3d7-2249240decb7.mp3" },
  { id: "TX3LPaxmHKxFdv7VOQHJ", name: "Liam", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/TX3LPaxmHKxFdv7VOQHJ/63148076-6363-42db-aea8-31424308b92c.mp3" },
  { id: "Xb7hH8MSUJpSbSDYk0k2", name: "Alice", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/Xb7hH8MSUJpSbSDYk0k2/d10f7534-11f6-41fe-a012-2de1e482d336.mp3" },
  { id: "XrExE9yKIg1WjnnlVkGX", name: "Matilda", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/XrExE9yKIg1WjnnlVkGX/b930e18d-6b4d-466e-bab2-0ae97c6d8535.mp3" },
  { id: "bIHbv24MWmeRgasZH58o", name: "Will", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/bIHbv24MWmeRgasZH58o/8caf8f3d-ad29-4980-af41-53f20c72d7a4.mp3" },
  { id: "cgSgspJ2msm6clMCkdW9", name: "Jessica", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/cgSgspJ2msm6clMCkdW9/56a97bf8-b69b-448f-846c-c3a11683d45a.mp3" },
  { id: "cjVigY5qzO86Huf0OWal", name: "Eric", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/cjVigY5qzO86Huf0OWal/d098fda0-6456-4030-b3d8-63aa048c9070.mp3" },
  { id: "iP95p4xoKVk53GoZ742B", name: "Chris", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/iP95p4xoKVk53GoZ742B/3f4bde72-cc48-40dd-829f-57fbf906f4d7.mp3" },
  { id: "nPczCjzI2devNBz1zQrb", name: "Brian", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/nPczCjzI2devNBz1zQrb/2dd3e72c-4fd3-42f1-93ea-abc5d4e5aa1d.mp3" },
  { id: "onwK4e9ZLuTAKqWW03F9", name: "Daniel", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/onwK4e9ZLuTAKqWW03F9/7eee0236-1a72-4b86-b303-5dcadc007ba9.mp3" },
  { id: "pFZP5JQG7iQjIQuC4Bku", name: "Lily", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/pFZP5JQG7iQjIQuC4Bku/89b68b35-b3dd-4348-a84a-a3c13a3c2b30.mp3" },
  { id: "pNInz6obpgDQGcFmaJgB", name: "Adam", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/pNInz6obpgDQGcFmaJgB/d6905d7a-dd26-4187-bfff-1bd3a5ea7cac.mp3" },
  { id: "pqHfZKP75CvOlQylNhV4", name: "Bill", preview: "https://storage.googleapis.com/eleven-public-prod/premade/voices/pqHfZKP75CvOlQylNhV4/d782b3ff-84ba-4029-848c-acf01285524d.mp3" },
];

export async function streamSpeech(text: string, signal?: AbortSignal): Promise<void> {
  const voiceId = useSettings.getState().ttsVoiceId;
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voiceId}/stream`, {
    method: "POST",
    headers: {
      "xi-api-key": ELEVENLABS_API_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text,
      model_id: MODEL_ID,
      output_format: "mp3_22050_32",
    }),
    signal,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`ElevenLabs ${res.status}: ${body.slice(0, 200)}`);
  }

  const contentType = res.headers.get("content-type") || "";

  if (contentType.includes("audio/mpeg") || contentType.includes("audio/mp3")) {
    return playStreamedAudio(res.body!, signal);
  }

  // Fallback: read as blob and play
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  if (signal) {
    signal.addEventListener("abort", () => { audio.pause(); URL.revokeObjectURL(url); });
  }
  await new Promise<void>((resolve, reject) => {
    audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
    audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Audio playback failed")); };
    audio.play().catch(reject);
  });
}

async function playStreamedAudio(body: ReadableStream<Uint8Array>, signal?: AbortSignal): Promise<void> {
  const mediaSource = new MediaSource();
  const audio = new Audio();
  audio.src = URL.createObjectURL(mediaSource);

  if (signal) {
    signal.addEventListener("abort", () => {
      audio.pause();
      URL.revokeObjectURL(audio.src);
    });
  }

  await new Promise<void>((resolve, reject) => {
    mediaSource.addEventListener("sourceopen", async () => {
      let sourceBuffer: SourceBuffer;
      try {
        sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
      } catch {
        // MediaSource doesn't support mpeg — fall back to blob approach
        const reader = body.getReader();
        const chunks: Uint8Array[] = [];
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
        }
        const blob = new Blob(chunks as BlobPart[], { type: "audio/mpeg" });
        audio.src = URL.createObjectURL(blob);
        audio.onended = () => { URL.revokeObjectURL(audio.src); resolve(); };
        audio.onerror = () => { URL.revokeObjectURL(audio.src); reject(new Error("Playback failed")); };
        audio.play().catch(reject);
        return;
      }

      const reader = body.getReader();
      const queue: Uint8Array[] = [];
      let ended = false;

      const appendNext = () => {
        if (sourceBuffer.updating) return;
        if (queue.length === 0) {
          if (ended && mediaSource.readyState === "open") mediaSource.endOfStream();
          return;
        }
        sourceBuffer.appendBuffer(queue.shift()!.buffer as ArrayBuffer);
      };

      sourceBuffer.addEventListener("updateend", appendNext);

      audio.onended = () => { URL.revokeObjectURL(audio.src); resolve(); };
      audio.onerror = () => { URL.revokeObjectURL(audio.src); reject(new Error("Playback failed")); };
      audio.play().catch(reject);

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (signal?.aborted) break;
        if (done) {
          ended = true;
          appendNext();
          break;
        }
        queue.push(value);
        appendNext();
      }
    }, { once: true });
  });
}
