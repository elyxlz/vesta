# The voice engine socket

`GET /voice/session` on the voice service is one WebSocket for one voice session. A client sends mic audio and the text to speak. The engine sends turn events and the audio to play. The engine knows nothing about chats, history, or who the client is: the client owns the conversation, the queue of its device, and when a session starts and ends.

Reach the service the way you reach any service of this box (see the `vestad` skill): on its port from inside the container (`voice daemon status` prints it), or through vestad with a service key from outside. The engine checks no credential itself.

Each text frame is a JSON object with `type`, and its fields are flat beside it. Ignore a frame type and a field that you do not know: new ones can appear.

## The session in one picture

```
client                                engine
  start_session                 →
                                ←     state {listening}
  (binary mic audio, all the time)
                                ←     transcript {"what is the"}
                                ←     turn_start
                                ←     state {user_turn}
                                ←     turn_end {"What is the weather?"}
                                ←     state {listening}
  speak {id, text}              →
                                ←     play {id, format, url}
  playback {id, started}        →
                                ←     state {agent_speaking}
  playback {id, finished}       →
                                ←     state {listening}
  end_session                   →
                                ←     ended {client_ended}
```

## Client → engine

| Frame | Meaning |
| --- | --- |
| `start_session {client, audio, playback, barge_in?}` | Starts the session. It is the first frame and it is sent one time. The engine answers with `state` or `ended`. |
| binary | Mic audio in the declared format. Send it for the whole session, also while a reply plays. |
| `speak {id, text}` | Say this text. `id` is your own id for the reply. Synthesis starts at once and a `play` follows. |
| `playback {id, state}` | What your speaker did with a play (see Playback reports). |
| `end_turn` | The user finished talking now (a button, a release of push-to-talk). The engine commits the open turn. |
| `end_session` | Ends the session. The engine sends `ended {reason: "client_ended"}` and closes. |

```json
{
  "type": "start_session",
  "client": "voice-home",
  "audio": {"encoding": "pcm_s16le", "sample_rate": 16000, "channels": 1},
  "playback": {"delivery": "url", "formats": ["mp3_22050"]},
  "barge_in": true
}
```

- `client`: the name of your client. The engine uses it only in logs.
- `audio`: the engine accepts exactly `pcm_s16le`, 16000 Hz, 1 channel. Any other value ends the session with `unsupported_format`.
- `playback.delivery`: `"url"` means you fetch each play. `"bytes"` means the engine sends the audio on this socket.
- `playback.formats`: an ordered list, first preferred, from `mp3_22050`, `mp3_44100`, `pcm_16000`, `pcm_22050`, `pcm_24000`, `ulaw_8000`, `opus_48000`. The engine takes the first one the selected TTS provider can make. `mp3_22050`, `pcm_16000`, `pcm_24000`, and `ulaw_8000` work with every shipped provider, so list one of them. With no TTS provider the list is not checked.
- `barge_in`: optional. `false` says that this session cannot do barge-in: dictation, or a device whose mic hears its own speaker. An absent field counts as `true`. Barge-in happens only when this is not `false` and the user's `barge_in` behavior is on.

A frame before `start_session`, and a second `start_session`, gets `error` and changes nothing.

## Engine → client

| Frame | Meaning | What you do |
| --- | --- | --- |
| `state {value}` | `listening`, `user_turn`, `agent_speaking`, or `agent_paused`. Sent on each change. | Show it. |
| `transcript {text}` | The live text of what the mic hears now. Empty text means that the text before it is over and no other frame says what became of it. | Show it. |
| `turn_start` | A turn said to the agent started. The user holds the floor. | Hold replies back. |
| `turn_end {text}` | The turn is over. `text` goes to the agent and is never empty. | Deliver it. |
| `turn_dropped {text, kind}` | A started turn is over and does not go to the agent. `kind` is null when the text is empty. | Deliver nothing. |
| `ignored {text, kind}` | Text was heard and no turn started. | Nothing. You can show it. |
| `play {id, format, url?}` | Play this after the plays before it, in arrival order. `url` is there in `url` delivery only. | Queue it, play it, report `playback`. |
| `play_done {id}` | Every byte of this play was sent (`bytes` delivery only). | Close this play's buffer. |
| `pause_playback` | Pause the audio now and keep the queue. | Pause. |
| `resume_playback` | Continue the paused audio. | Continue. |
| `stop_playback {id, dropped}` | Stop the audio and clear the queue. `id` is the play that was cut, or null. `dropped` lists the plays that never started. | Stop, clear, and discard buffered bytes. |
| `error {message}` | Something failed. The session continues. | Show or log it. |
| `ended {reason}` | The session is over. | Close. |

`kind` is `backchannel` (a short sound while the agent speaks, such as "mhm"), `echo` (the agent's own voice in the mic), `other_person`, or `not_speech`.

A socket that closes with no `ended` frame means the engine failed or the network dropped. When the engine itself failed, an `error` frame that says so comes right before the close. Open a new session in both cases.

`ended.reason`: `client_ended`, `stt_failed` (the STT provider refused or dropped the connection), `stt_limit` (the provider is at its limit of sessions at the same time), `not_configured` (the `stt` role is off or has no provider), `unsupported_format`.

## States

| State | Meaning |
| --- | --- |
| `listening` | The mic is open. No turn is open and nothing plays. |
| `user_turn` | A turn said to the agent is open. |
| `agent_speaking` | A play started and the queue is not empty yet. |
| `agent_paused` | Playback is paused while the engine decides if the user takes the floor. |

In `user_turn` the engine holds a new `play` and sends it after `turn_end` or `turn_dropped`. In every other state it sends each `play` at once.

The STT provider decides when a turn ends: you do not need a silence timer. Send `end_turn` only when the user ends the turn by hand.

## Playback

The engine does not pace the plays: it sends each one as soon as it can, and you play them in arrival order. A device that holds one item at a time keeps its own queue.

**`url` delivery.** `play {id, format, url}`. `url` is a path on the voice service, such as `/voice/play/<token>`: fetch it as given, beside the path you opened the socket on. The audio streams while it is made, so start to play at the first byte. The engine keeps the audio of a play until your speaker is done with it: a token answers 404 after you report its play `finished` or `failed`, after a `stop_playback` that cut or dropped it, and after its session ends.

**`bytes` delivery.**

1. `play {id, format}`
2. binary frames with the audio of this play, in order
3. `play_done {id}`

Binary frames from the engine always belong to the last `play` that has no `play_done` yet: the bytes of two plays never mix. On `pause_playback`, keep buffering the bytes that arrive.

**Playback reports** describe your speaker, not the socket, and they are the same in both deliveries:

| `state` | Exact meaning |
| --- | --- |
| `started` | The first sample of this play reached the speaker. |
| `finished` | The last sample of this play has played. |
| `failed` | You could not play it. |
| `stopped_by_user` | The user stopped it on the device. The engine answers with `stop_playback`. |

Send them truthfully and on time: the engine knows that the agent is speaking only from `started`, and it listens for a barge-in only between `started` and the last `finished`. A reply that you never report as `started` can never be interrupted by voice.

## Sessions at the same time

One socket is one session, and a session shares nothing with any other. Two sessions can speak the same `id`: each gets its own audio and its own `url`. A `stop_playback` in one session stops nothing in another. The engine does not know that two sessions belong to one user, so a client that opens two keeps them apart itself.
