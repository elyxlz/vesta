# Developing the WhatsApp CLI

Internal notes for changing the `whatsapp` skill. The agent does not need this;
its whole surface is `connect`, `status`, `send`, `messages`, `profile`, calls
(see [SKILL.md](SKILL.md)).

## How it runs

The CLI runs as a background **daemon** (`whatsapp serve`), launched detached in
its own session with its pid recorded at
`~/agent/data/daemons/whatsapp[-<instance>].pid` and its output appended to
`~/agent/logs/whatsapp[-<instance>].log`. One-shot commands (`send`, `status`,
`messages`, ...) connect to it over a Unix socket. Every agent-facing command
self-bootstraps the daemon, so the agent never starts, stops, or restarts
anything by hand. At boot the restart skill runs `whatsapp daemon start`, which
is idempotent and returns only once the daemon answers, so notifications are
already flowing before the agent sends anything; `setup.sh` prints that line for
the agent to add.

That pid record is also the mutual exclusion: a start claims it (exclusive create)
before it spawns anything and drops it again on every failure, so two starts
landing at once leave one daemon and a record that names it. A daemon serving the
instance that this lifecycle did not start (so the record is empty and the
device-store lock is held elsewhere) is the one case it refuses: start and restart
say so instead of reporting a success no record stands behind. End that process
first.

`daemon stop` sends SIGTERM to the recorded pid and waits for the process to go.
SIGTERM is therefore the one exit the agent asked for, and the only one the
daemon leaves unreported: it writes a `daemon_died` notification on every other
way out (`deathIsNews` in `daemon.go`).

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
(`stateStore`: a pure load + atomic temp+rename save). It holds the independent
primary mode, number source, API transport, opaque number-lease reference,
self-hosted Double Tick credentials when applicable, auth-status cache, last-exit
reason, daemon-info, pairing-attempts, and linked-at. It never stores Vesta Cloud
or Double Tick service credentials. The serve process is the **sole writer**; transient CLI commands only read
it (and only when no daemon answers the socket, so there is no cross-process write
clobber). On first start the daemon imports any legacy per-key files it finds into
`state.json` and deletes them (lossless, idempotent). `daemon.log`
(the ~5 MB self-capping debug log), `qr-code.png`, `daemon.lock`, and
`whatsapp.sock` are NOT state and stay separate.

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
- `--instance <name>`: a second, isolated account/session under `~/.whatsapp/<name>/` (its own lock, socket, daemon.log, and `whatsapp-<name>` pid record).
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
