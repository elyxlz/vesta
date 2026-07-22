# Developing the WhatsApp CLI

Internal notes for changing the `whatsapp` skill. The agent does not need this;
its whole surface is `provision`, `status`, `send`, `messages`, `profile`, calls
(see [SKILL.md](SKILL.md)).

## How it runs

The CLI runs as a background **daemon** (`whatsapp serve`) under `screen`.
One-shot commands (`send`, `status`, `messages`, ...) connect to it over a Unix
socket. Every agent-facing command self-bootstraps the daemon, so the agent never
starts, stops, or restarts anything by hand. At boot the restart skill runs
`whatsapp start` (an idempotent front door to the daemon-lifecycle start: it
brings the daemon up and waits until it answers, so notifications are already
flowing before the agent sends anything); `setup.sh` registers that line.

The daemon holds an exclusive OS lock on `<dataDir>/daemon.lock` for its whole
lifetime (`acquireDaemonLock`, taken in `runServe` before the whatsmeow store is
opened). A second `serve` on the same data dir prints `{"status":"already_running"}`
and exits without connecting, so two clients can never share one device identity
(the device-session conflict that caused repeated logouts).

### The daemon's job is small

The serve process does exactly three things: **maintain a linked connection**
(connect if `Store.ID != nil`, reconnect transient drops), **serve the socket**,
and **emit notifications**. It never auto-pairs. On boot, an unlinked device stays
IDLE (socket up, not connected); pairing happens only through a deliberate,
foreground `whatsapp provision` / `whatsapp link`. So no background pairing
goroutine can race an explicit command.

### One state file, one owner

All daemon state lives in a single `<dataDir>/state.json` owned by `state.go`
(`stateStore`: a pure load + atomic temp+rename save). It folds what used to be six
separate files (managed number + pool creds, auth-status cache, last-exit reason,
daemon-info, pairing-attempts, linked-at). The serve process is the **sole writer**;
transient CLI commands only read it (and only when no daemon answers the socket, so
there is no cross-process write clobber). On first start the new daemon imports any
legacy files into `state.json` and deletes them (lossless, idempotent). `daemon.log`
(the ~5 MB self-capping debug log), `qr-code.png`, `daemon.lock`, `whatsapp.sock`,
and the `stop-requested` IPC marker are NOT state and stay separate.

### One pairing primitive

`provision` (managed) and `link` (self-hosted QR) are the only pairing drivers, each
run synchronously in the socket-command handler and **single-flighted** through
`beginPairing` (one pairing at a time). Each is self-contained: set up channel ->
connect -> pair -> wait -> return a terminal result, leaving the client CLEAN
(disconnected) on every failure so the next attempt works. The paradigm is chosen
once at construction behind the `linker` interface (`linker.go`: `qrLinker` /
`managedLinker`, `chooseLinker` from config); the daemon never branches on mode
inline. The connection posture is one atomic `connMode` (normal / pairing /
parked) that every reconnect path honors.

### Churn-free logout handling

`events.go` (`classifyConnEvent`) is deliberately churn-free: a transient
`Disconnected` is ignored (whatsmeow auto-reconnects); a `StreamReplaced` records
the reason and **parks** (`connParked`: stays up, but no reconnect path will
reconnect, so it never fights the other holder); a genuine `LoggedOut` records the
reason, notifies the agent, drops the dead session, and **exits 0** so the next
serve boots a fresh device for a deliberate re-link. Re-linking is only ever a
deliberate `whatsapp provision` / `whatsapp link`, never an automatic loop.

## Internal / dev-only commands

Not part of the agent's vocabulary, kept for development:
- `whatsapp daemon <start|stop|restart|status>` manages the daemon explicitly.
- `whatsapp serve [flags]` runs it in the foreground.
- `whatsapp authenticate` prints auth status (alias of `status`, back-compat).
- `whatsapp update-deps` bumps the pinned whatsmeow (deliberately, not mid-session).

### `serve` flags

- `--notifications-dir <dir>` (default `~/agent/notifications`): where inbound notification JSON is written.
- `--no-notifications`: write no notification files (messages are still stored and queryable).
- `--instance <name>`: a second, isolated account/session under `~/.whatsapp/<name>/` (its own lock, socket, and daemon.log).
- `--read-only`: passive mode. Blocks every write command, sends no read receipts, never broadcasts presence.
- `--skip-senders <phone,phone,...>`: E.164 numbers whose inbound messages never notify (still stored).

Recipe, a fully silent passive personal account:
```bash
whatsapp serve --instance personal --read-only --no-notifications
```
Link it with `whatsapp link --instance personal`; read it on demand
(`whatsapp chats --instance personal`, `messages`, ...) with zero notifications.

## Never ship a static binary

`whatsapp` must stay the launcher symlink (`~/.local/bin/whatsapp` ->
`~/agent/skills/whatsapp/whatsapp`), which builds from source and caches the
binary, rebuilding only when a source input changed (issue #1073). whatsmeow is
PINNED in `cli/go.mod`; bump it deliberately via `whatsapp update-deps`, then
`whatsapp daemon restart`. `serve` only WARNS when a newer whatsmeow exists
(auto-floating it mid-session can log the device out).

## Building and testing

```bash
cd cli && source ./cgo-env.sh   # whisper cgo env
gofmt -l .
go build -tags fts5 ./...
go vet -tags fts5 ./...
go test -tags fts5 ./...
```
The deterministic pieces (single-instance lock, event classification, status
mapping, daemon-log cap, PCM framing, notification shape, no-active-call guards)
are covered by `go test`. Testing calls end to end needs a second WhatsApp
account plus a configured `voice` skill, so it is a manual check: with the daemon
running, `whatsapp call --to '<other number>'`, answer on the other phone, then
`whatsapp say 'hello'` and confirm you hear it and a `call_utterance` lands.

**If the daemon won't come up after a change**, run any foreground command (e.g.
`whatsapp --help`): the launcher recompiles and prints the compile error. If
WhatsApp broke old protocol code, `whatsapp update-deps` and fix the source
against the new API rather than pinning back.
