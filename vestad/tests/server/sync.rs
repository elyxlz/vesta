//! `/sync` WebSocket integration scenarios, driven end-to-end against a real vestad + agent
//! container through the T1 harness `SyncSocket`. Fake-token agents settle unprovisioned and run no
//! model, so a helper starts their app-chat daemon by hand (`start_app_chat_daemon`, docker exec);
//! that daemon owns the skill service the sends target and emits the live echo these appends ride on,
//! so no real model is needed. A container restart kills the daemon, so scenarios that restart an
//! agent start it again before driving the next append.
//!
//! Two spec sub-scenarios are deliberately absent: sub-floor client rejection (D2, dropped — the
//! server always speaks protocol 1 and never rejects; the floor is a client-side gate) and the
//! reauth deadline-expiry timer (D3, covered in the handler unit tier via `token_deadline`/`expire`).
//! This module owns the socket-observable behaviors only.

use std::collections::HashSet;
use std::time::{Duration, Instant};

use vesta_tests::client::{Client, SyncSocket};
use vesta_tests::{inject_fake_token, unique_agent, TestAgent, SERVER, SHARED_RO_AGENT};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 90;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
/// Total budget for a driven append to round-trip (HTTP relay -> agent echo -> tap -> watch).
const APPEND_TIMEOUT: Duration = Duration::from_secs(45);
/// Per-resend read window inside `drive_and_expect_append`.
const APPEND_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(4);
/// Window over which an unwatched agent must stay silent.
const SILENCE_WINDOW: Duration = Duration::from_secs(6);
/// A container restart plus tap reconnect is slow; give the resync room.
const RESYNC_TIMEOUT: Duration = Duration::from_secs(120);
/// How long to poll (via reconnect) for a fresh agent to surface in a snapshot.
const SNAPSHOT_POLL_TIMEOUT: Duration = Duration::from_secs(30);

// D2: the wire protocol version + floor, mirrored from apps/core/src/protocol/version.ts and
// vestad's crate-private `sync::PROTOCOL_VERSION` / `sync::PROTOCOL_FLOOR` (not importable from an
// integration crate, so pinned to the contract literals here).
const EXPECT_PROTOCOL: u64 = 1;
const EXPECT_FLOOR: u64 = 1;

/// Create a fake-token agent and bring it up to a live tap. Fake-token agents settle at
/// `unprovisioned`/`not_authenticated`, enough to exercise frame plumbing (no real model needed).
/// The app-chat echo the appends ride on is emitted by the skill daemon, which a model-less agent
/// never boots itself, so start it by hand once the agent is up.
fn running_agent<'a>(c: &'a Client, prefix: &str) -> TestAgent<'a> {
    let agent = TestAgent::create(c, &unique_agent(prefix)).expect("create agent");
    inject_fake_token(c, &agent.name);
    c.start_agent(&agent.name).expect("start agent");
    c.wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running");
    c.start_app_chat_daemon(&agent.name)
        .expect("start app-chat daemon");
    agent
}

/// Read the mandatory hello (asserting the protocol/floor contract) then the immediate snapshot,
/// returning the snapshot frame. Frames 1 and 2 are deterministically hello then snapshot (the
/// handler sends both before entering its select loop).
async fn handshake(sock: &mut SyncSocket) -> serde_json::Value {
    let hello = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("hello frame");
    assert_eq!(hello["type"].as_str(), Some("hello"), "first frame is hello");
    assert_eq!(hello["protocol"].as_u64(), Some(EXPECT_PROTOCOL), "hello protocol per D2");
    assert_eq!(hello["floor"].as_u64(), Some(EXPECT_FLOOR), "hello floor per D2");
    let snapshot = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("snapshot frame");
    assert_eq!(snapshot["type"].as_str(), Some("snapshot"), "second frame is snapshot");
    snapshot
}

/// True when a harness `recv_frame`/`expect_frame_matching` error string signals a real socket
/// close/end/transport-failure, false for a plain read timeout ("timed out waiting for sync frame").
/// Keeps a close assertion from being satisfied by the deadline merely elapsing on a still-open socket.
fn is_close_error(msg: &str) -> bool {
    msg.contains("closed") || msg.contains("ended") || msg.contains("socket error")
}

fn is_append_for(frame: &serde_json::Value, agent: &str, intent: &str) -> bool {
    frame["type"].as_str() == Some("append")
        && frame["agent"].as_str() == Some(agent)
        && frame["events"]
            .as_array()
            .is_some_and(|events| events.iter().any(|e| e["intent_id"].as_str() == Some(intent)))
}

/// Drive one app-chat message onto `agent`'s tap and return the `append` echo carrying `intent`.
/// Re-sends on a bounded cadence until the append lands: the tap may not have installed its
/// write-half yet (send 503s) and a just-issued watch may not have subscribed before the first
/// echo. A resend closes both races deterministically because the watch stays registered and each
/// send emits a fresh echo carrying the same intent id.
async fn drive_and_expect_append(
    c: &Client,
    sock: &mut SyncSocket,
    agent: &str,
    text: &str,
    intent: &str,
) -> serde_json::Value {
    let deadline = Instant::now() + APPEND_TIMEOUT;
    // Track only the MOST RECENT send outcome: a stale error would mislead (a 503 before the tap
    // installs, then successful sends whose echo never lands, are two different failures).
    let mut last_send_err: Option<String>;
    loop {
        match c.send_message(agent, text, Some(intent)) {
            Ok(()) => last_send_err = None,
            Err(e) => last_send_err = Some(e),
        }
        if let Ok(frame) = sock
            .expect_frame_matching(|f| is_append_for(f, agent, intent), APPEND_ATTEMPT_TIMEOUT)
            .await
        {
            return frame;
        }
        assert!(
            Instant::now() < deadline,
            "no append for {agent} intent {intent} within {APPEND_TIMEOUT:?} (last send error: {last_send_err:?})"
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// Assert no `append` for `agent` carrying `intent` arrives within `window`. Other frames (roster
/// deltas, notifications) are drained and allowed. Bounded read loop, never a bare sleep-to-await.
async fn assert_no_append(sock: &mut SyncSocket, agent: &str, intent: &str, window: Duration) {
    let deadline = Instant::now() + window;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return;
        }
        match sock.recv_frame(remaining).await {
            Ok(frame) => assert!(
                !is_append_for(&frame, agent, intent),
                "an unwatched agent still delivered an append: {frame}"
            ),
            // Timeout (or a benign close): no matching append arrived within the window.
            Err(_) => return,
        }
    }
}

/// Relay a send-message, retrying briefly past a transient tap-down 503. Returns once the relay is
/// accepted (the append echo is the delivery truth, asserted separately by the caller).
async fn ensure_send(c: &Client, agent: &str, text: &str, intent: &str) {
    let deadline = Instant::now() + Duration::from_secs(20);
    loop {
        if c.send_message(agent, text, Some(intent)).is_ok() {
            return;
        }
        assert!(Instant::now() < deadline, "tap never accepted the send for {agent}");
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// (1) The first two frames are `hello` (with the D2 protocol/floor constants) then a `snapshot`
/// whose `tree.agents` carries the agent with an `info` branch. Uses the shared read-only agent
/// (created, never mutated) and polls via reconnect until the status cache has surfaced it.
#[tokio::test]
async fn hello_then_snapshot_carries_agent_info_branch() {
    let c = SERVER.client();
    let agent = &*SHARED_RO_AGENT;
    let deadline = Instant::now() + SNAPSHOT_POLL_TIMEOUT;
    loop {
        let mut sock = c.open_sync().await.expect("open sync");
        let snapshot = handshake(&mut sock).await;
        if let Some(node) = snapshot["tree"]["agents"].get(agent.as_str()) {
            assert!(node.get("info").is_some(), "agent node carries an info branch");
            // The snapshot is tail-less by contract: roster + pending only, no event/chat tails.
            assert!(node.get("events").is_none(), "snapshot node carries no event tail");
            assert!(node.get("chat").is_none(), "snapshot node carries no chat tail");
            sock.close().await.ok();
            return;
        }
        sock.close().await.ok();
        assert!(
            Instant::now() < deadline,
            "agent {agent} never appeared in a /sync snapshot within {SNAPSHOT_POLL_TIMEOUT:?}"
        );
    }
}

/// (2) A `watch` delivers the agent's live edge as `append` deltas, and the echoed events carry an id.
#[tokio::test]
async fn watch_delivers_appends_with_ids() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-watch");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&agent.name).await.expect("watch");

    let append = drive_and_expect_append(&c, &mut sock, &agent.name, "hello from watch", "intent-watch").await;
    let event = append["events"]
        .as_array()
        .expect("events array")
        .iter()
        .find(|e| e["intent_id"].as_str() == Some("intent-watch"))
        .expect("the echoed event");
    assert!(event.get("id").is_some(), "appended events carry an id");
    sock.close().await.ok();
}

/// (3) After an `unwatch`, further live events for that agent stop reaching the socket.
#[tokio::test]
async fn unwatch_stops_delivery() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-unwatch");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&agent.name).await.expect("watch");
    drive_and_expect_append(&c, &mut sock, &agent.name, "before unwatch", "intent-before").await;

    sock.unwatch(&agent.name).await.expect("unwatch");
    // The unwatch frame is already at vestad while the next echo must round-trip to the container
    // and back, so the watch is torn down well before that echo could be published; a following
    // append for this agent would prove the unwatch didn't take.
    ensure_send(&c, &agent.name, "after unwatch", "intent-after").await;
    assert_no_append(&mut sock, &agent.name, "intent-after", SILENCE_WINDOW).await;
    sock.close().await.ok();
}

/// (4, D1) Restarting a watched agent yields exactly one `resync` for it (dropping its server-side
/// watch) while a second agent's watch keeps streaming; re-watching resumes appends.
#[tokio::test]
async fn resync_drops_watch_while_second_agent_streams() {
    let c = SERVER.client();
    let a = running_agent(&c, "sync-resync-a");
    let b = running_agent(&c, "sync-resync-b");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&a.name).await.expect("watch a");
    sock.watch(&b.name).await.expect("watch b");

    // Establish both live edges before the disruption.
    drive_and_expect_append(&c, &mut sock, &a.name, "a1", "a-before").await;
    drive_and_expect_append(&c, &mut sock, &b.name, "b1", "b-before").await;

    // Restart A: its tap gaps and re-attaches, emitting one resync for A. B's tap is untouched.
    c.restart_agent(&a.name).expect("restart a");
    sock.expect_frame_matching(
        |f| f["type"].as_str() == Some("resync") && f["agent"].as_str() == Some(a.name.as_str()),
        RESYNC_TIMEOUT,
    )
    .await
    .expect("a single resync for a");

    // B keeps streaming across A's restart (remove-on-resync scopes to A's watch only).
    drive_and_expect_append(&c, &mut sock, &b.name, "b2", "b-after").await;

    // The resync dropped A's server-side watch; re-watch and appends resume once A is back up. The
    // restart killed A's daemon with its process tree, so start it again before driving the append.
    c.wait_until_running(&a.name, AGENT_RUNNING_TIMEOUT_SECS).expect("a back up");
    c.start_app_chat_daemon(&a.name).expect("restart a's app-chat daemon");
    sock.watch(&a.name).await.expect("re-watch a");
    drive_and_expect_append(&c, &mut sock, &a.name, "a2", "a-after").await;
    sock.close().await.ok();
}

/// (5, D3) A garbage `reauth` on a raw-key socket closes it; a valid `reauth` on a JWT socket keeps
/// it open and still delivers a subsequent append.
#[tokio::test]
async fn reauth_extends_and_closes_on_bad() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-reauth");

    // (a) raw-key socket + a bad reauth -> the server breaks the loop and closes the socket.
    let mut raw = c.open_sync().await.expect("open raw sync");
    handshake(&mut raw).await;
    raw.reauth("bad.token.here").await.expect("send bad reauth");
    let deadline = Instant::now() + HANDSHAKE_TIMEOUT;
    let closed = loop {
        match raw
            .recv_frame(deadline.saturating_duration_since(Instant::now()))
            .await
        {
            // Tolerate any in-flight frame queued before the reauth was processed; keep reading.
            Ok(_) if Instant::now() < deadline => {}
            // Still open at the deadline: not closed. A read timeout is the same signal, so it must
            // not count as a close (that is exactly the regression this distinguishes).
            Ok(_) => break false,
            Err(ref e) => break is_close_error(e),
        }
    };
    assert!(closed, "a bad reauth must close the socket (a read timeout is not a close)");

    // (b) JWT socket + a valid reauth -> stays open and still delivers an append.
    let jwt = c.mint_access_token().expect("mint jwt");
    let mut tok = c.open_sync_with_token(&jwt.access_token).await.expect("open jwt sync");
    handshake(&mut tok).await;
    tok.watch(&agent.name).await.expect("watch");
    let fresh = c.mint_access_token().expect("mint fresh jwt");
    tok.reauth(&fresh.access_token).await.expect("send valid reauth");
    drive_and_expect_append(&c, &mut tok, &agent.name, "after reauth", "intent-reauth").await;
    tok.close().await.ok();
}

/// (6) Unknown/malformed client frames are ignored; a following `watch` still works, proving the
/// socket stayed live.
#[tokio::test]
async fn unknown_client_frames_are_ignored() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-unknown");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    // An unknown `type` and a non-object frame both fail ClientFrame parsing and are dropped.
    sock.send_client_frame(&serde_json::json!({ "type": "future", "x": 1 }))
        .await
        .expect("send unknown frame");
    sock.send_client_frame(&serde_json::json!("garbage-not-a-frame"))
        .await
        .expect("send malformed frame");

    // The socket stayed live: a following watch still delivers.
    sock.watch(&agent.name).await.expect("watch");
    drive_and_expect_append(&c, &mut sock, &agent.name, "still alive", "intent-unknown").await;
    sock.close().await.ok();
}

/// Drive one app-chat message and return the string form of the echoed event's `id` (the events.db
/// row id). Fails exactly as `drive_and_expect_append` does if no append lands within the budget.
async fn driven_event_id(c: &Client, sock: &mut SyncSocket, agent: &str, text: &str, intent: &str) -> String {
    let append = drive_and_expect_append(c, sock, agent, text, intent).await;
    let event = append["events"]
        .as_array()
        .expect("events array")
        .iter()
        .find(|e| e["intent_id"].as_str() == Some(intent))
        .expect("the echoed event");
    assert!(event.get("id").is_some(), "echoed event carries an id");
    event["id"].to_string()
}

/// (7) `send_message` with an explicit intent id round-trips end-to-end: the `append` echo carries
/// the SAME `intent_id` the HTTP relay was given (HTTP intent -> tap -> live edge), the delivery-truth
/// contract clients dedup and confirm on.
#[tokio::test]
async fn send_message_intent_id_echoes_on_the_append() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-intent");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&agent.name).await.expect("watch");

    let intent = "i-2f8c1a90-send-echo";
    let append = drive_and_expect_append(&c, &mut sock, &agent.name, "carry my intent", intent).await;
    let event = append["events"]
        .as_array()
        .expect("events array")
        .iter()
        .find(|e| e["intent_id"].as_str() == Some(intent))
        .expect("the echoed event");
    assert_eq!(
        event["intent_id"].as_str(),
        Some(intent),
        "the append echo carries the exact intent id the send was given"
    );
    sock.close().await.ok();
}

/// (8) A watched agent restarted mid-stream keeps the SAME container (its events.db persists, so ids
/// stay monotonic); the tap gaps then reconnects, emitting one `resync` that drops this agent's
/// server-side watch. After re-watching, appends resume. The union of the event ids seen before the
/// restart and after it has no repeats: the live edge never replays across the gap, so a client
/// deduping by id gains no duplicate across the seam. (The paged-history reseed that fills the gap is
/// the client controller's job, unit-tested.)
#[tokio::test]
async fn restart_reseeds_without_duplicate_ids() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-restart");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&agent.name).await.expect("watch");

    let mut ids: Vec<String> = Vec::new();
    ids.push(driven_event_id(&c, &mut sock, &agent.name, "before-1", "kb-1").await);
    ids.push(driven_event_id(&c, &mut sock, &agent.name, "before-2", "kb-2").await);

    // Restart the same container (events.db persists, so ids stay monotonic). The tap gaps then
    // reconnects, emitting one resync that drops this agent's server-side watch.
    c.restart_agent(&agent.name).expect("restart agent");
    sock.expect_frame_matching(
        |f| f["type"].as_str() == Some("resync") && f["agent"].as_str() == Some(agent.name.as_str()),
        RESYNC_TIMEOUT,
    )
    .await
    .expect("a resync after the restart");

    // The restart killed the daemon with the container's process tree; start it again before driving.
    c.wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent back up");
    c.start_app_chat_daemon(&agent.name)
        .expect("restart the app-chat daemon");
    sock.watch(&agent.name).await.expect("re-watch");
    ids.push(driven_event_id(&c, &mut sock, &agent.name, "after-1", "ka-1").await);
    ids.push(driven_event_id(&c, &mut sock, &agent.name, "after-2", "ka-2").await);

    let unique: HashSet<&String> = ids.iter().collect();
    assert_eq!(
        unique.len(),
        ids.len(),
        "event ids across the restart seam must not repeat: {ids:?}"
    );
    sock.close().await.ok();
}

/// (9) A `watch` for an agent that does not exist yet is accepted (the hub creates the live-edge
/// channel lazily via `subscribe_events`); once the agent is created and its tap attaches, the roster
/// `agent` upsert and then appends flow to that pre-registered watch. Bounded generously: agent
/// creation (image build/pull + container boot) is slow.
#[tokio::test]
async fn watch_before_create_is_held_until_the_agent_materializes() {
    let c = SERVER.client();
    // The name the agent will take: `unique_agent` yields an already-normalized name, so the watch
    // key matches the container the create produces (asserted below, guarding a future rename rule).
    let name = unique_agent("sync-precreate");

    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    // Accepted with no error though the agent is absent; the hub creates the channel lazily.
    sock.watch(&name).await.expect("watch before create");

    let agent = TestAgent::create(&c, &name).expect("create agent");
    assert_eq!(agent.name, name, "created name matches the pre-watched key");
    inject_fake_token(&c, &agent.name);
    c.start_agent(&agent.name).expect("start agent");
    c.wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running");
    c.start_app_chat_daemon(&agent.name)
        .expect("start app-chat daemon");

    // The roster upsert for the freshly created agent reaches this held session.
    sock.expect_frame_matching(
        |f| f["type"].as_str() == Some("agent") && f["name"].as_str() == Some(name.as_str()),
        RESYNC_TIMEOUT,
    )
    .await
    .expect("roster upsert for the new agent");

    // The pre-registered watch delivers appends once the tap attaches.
    drive_and_expect_append(&c, &mut sock, &agent.name, "hello held watch", "i-held-watch").await;
    sock.close().await.ok();
}
