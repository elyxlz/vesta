//! `/sync` WebSocket integration scenarios, driven end-to-end against a real vestad + agent
//! container through the T1 harness `SyncSocket`. The state plane carries roster + snapshot + pending
//! notifications + `reauth` + the always-on `user_notification` delta; it no longer transports chat.
//! Chat lives wholly on the app-chat service: its echo streams on the per-connection chat socket
//! (`GET /agents/{name}/app-chat/ws` through the proxy, `open_app_chat_socket`), replay-free, so the
//! send/echo scenario opens that socket and reads the echo carrying its `intent_id` there. User
//! notifications (a new reply, a rate limit) come from the agent-side user-notification primitive
//! looped back through vestad (`POST /agents/{name}/user-notification`, `X-Agent-Token`), which fans a
//! `user_notification` delta to every connected session; the user-notification scenario exercises that
//! path and the closed-kind 400, and the reauth/unknown scenarios reuse it as a liveness probe.
//!
//! Fake-token agents settle unprovisioned and run no model, so a helper starts their app-chat daemon
//! by hand (`start_app_chat_daemon`, docker exec); that daemon owns the skill service the sends target
//! and fans the live echo the chat socket reads, so no real model is needed.
//!
//! Two spec sub-scenarios are deliberately absent: below-window client rejection (D2, dropped, since
//! the server never rejects; the served version window is a client-side gate) and the reauth
//! deadline-expiry timer (D3, covered in the handler unit tier via `token_deadline`/`expire`).
//! This module owns the socket-observable behaviors only.

use std::time::{Duration, Instant};

use vesta_tests::client::{Client, SyncSocket};
use vesta_tests::{inject_fake_token, unique_agent, TestAgent, SERVER, SHARED_RO_AGENT};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 90;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
/// Total budget for a chat-socket echo to round-trip (HTTP intake -> daemon persist -> chat-socket).
const CHAT_ECHO_TIMEOUT: Duration = Duration::from_secs(45);
/// Per-resend read window inside `drive_and_expect_echo`.
const CHAT_ECHO_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(4);
/// The proxy 404s the chat-socket upgrade until `register-service` records the daemon's port, so the
/// open is retried briefly over this window.
const CHAT_SOCKET_OPEN_TIMEOUT: Duration = Duration::from_secs(30);
/// Budget for a user notification to fan its `user_notification` delta to a connected session (loopback POST -> broadcast).
const USER_NOTIFICATION_TIMEOUT: Duration = Duration::from_secs(20);
/// How long to poll (via reconnect) for a fresh agent to surface in a snapshot.
const SNAPSHOT_POLL_TIMEOUT: Duration = Duration::from_secs(30);

// D2: the served compatibility window's low end, mirrored from vestad's crate-private
// `sync::MIN_SUPPORTED_CLIENT_VERSION` (not importable from an integration crate, so pinned to the
// contract literal here). Dropping the device `location` field from the roster removed a wire field
// clients read, so the floor moved to the in-gap bump above the shipped version (see release.sh for
// the in-gap bump convention).
const EXPECT_MIN_SUPPORTED: &str = "0.2.5";

/// Create a fake-token agent and bring it up to a live tap. Fake-token agents settle at
/// `unprovisioned`/`not_authenticated`, enough to exercise frame plumbing (no real model needed). The
/// app-chat echo the chat socket reads is fanned by the skill daemon, which a model-less agent never
/// boots itself, so start it by hand once the agent is up.
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

/// Read the mandatory hello (asserting the served version window) then the immediate snapshot,
/// returning the snapshot frame. Frames 1 and 2 are deterministically hello then snapshot (the
/// handler sends both before entering its select loop).
async fn handshake(sock: &mut SyncSocket) -> serde_json::Value {
    let hello = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("hello frame");
    assert_eq!(hello["type"].as_str(), Some("hello"), "first frame is hello");
    assert!(hello["version"].as_str().is_some(), "hello carries the gateway version");
    assert_eq!(hello["min_supported"].as_str(), Some(EXPECT_MIN_SUPPORTED), "hello min_supported per D2");
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

/// Open the agent's app-chat chat socket, retrying briefly past a still-registering service: the proxy
/// 404s the ws upgrade until `register-service` records the daemon's port. Bounded, never a bare sleep.
async fn open_chat_socket(c: &Client, agent: &str) -> SyncSocket {
    let deadline = Instant::now() + CHAT_SOCKET_OPEN_TIMEOUT;
    loop {
        match c.open_app_chat_socket(agent).await {
            Ok(sock) => return sock,
            Err(e) => assert!(
                Instant::now() < deadline,
                "the app-chat chat socket never opened for {agent}: {e}"
            ),
        }
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// Drive one app-chat message onto `agent` and return the intent id it used plus the echo the chat
/// socket delivered for it. A fresh intent each attempt: the daemon dedups a repeated intent whole (no
/// re-echo), so a retry that closes the subscriber-registration race must carry a new id. The winning
/// echo proves both the send landed and the socket was subscribed for the reply that follows.
async fn drive_and_expect_echo(
    c: &Client,
    sock: &mut SyncSocket,
    agent: &str,
    text: &str,
) -> (String, serde_json::Value) {
    let deadline = Instant::now() + CHAT_ECHO_TIMEOUT;
    let mut attempt = 0u32;
    let mut last_send_err: Option<String>;
    loop {
        let intent = format!("i-chat-echo-{attempt}");
        match c.send_message(agent, text, Some(&intent)) {
            Ok(()) => last_send_err = None,
            Err(e) => last_send_err = Some(e),
        }
        if let Ok(frame) = sock
            .expect_frame_matching(
                |f| f["intent_id"].as_str() == Some(intent.as_str()),
                CHAT_ECHO_ATTEMPT_TIMEOUT,
            )
            .await
        {
            return (intent, frame);
        }
        assert!(
            Instant::now() < deadline,
            "no chat-socket echo for {agent} within {CHAT_ECHO_TIMEOUT:?} (last send error: {last_send_err:?})"
        );
        attempt += 1;
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
}

/// Send a user notification to `agent` (kind `message`) over the loopback as the agent would, then
/// assert the resulting `user_notification` delta reaches `sock`. Doubles as a liveness probe: a
/// session still in its select loop receives the broadcast; a closed or wedged one never does.
async fn send_user_notification_and_expect_delta(c: &Client, sock: &mut SyncSocket, agent: &str, token: &str, body: &str) {
    c.send_user_notification(agent, token, "message", agent, body).expect("send user notification message");
    sock.expect_frame_matching(
        |f| f["type"].as_str() == Some("user_notification") && f["agent"].as_str() == Some(agent),
        USER_NOTIFICATION_TIMEOUT,
    )
    .await
    .expect("a user_notification delta for the user notification");
}

/// (1) The first two frames are `hello` (carrying the D2 served version window) then a `snapshot`
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

/// (2) `POST /agents/{name}/user-notification {kind:"message",...}` carrying the agent's own
/// `X-Agent-Token` fans a `user_notification` delta `{agent,kind,title,body}` to a connected `/sync`
/// session (the loopback path the app-chat reply hook and the rate-limit notice use). The kind is a
/// closed set: an unknown kind is a 400.
#[tokio::test]
async fn user_notification_message_fans_a_delta_and_rejects_unknown_kinds() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-notify");
    let token = c.read_agent_token(&agent.name).expect("read agent token");

    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    // A valid user notification (kind message, the app-chat reply hook's shape) fans a delta carrying
    // the closed-set kind and the title/body triple to the connected session.
    c.send_user_notification(&agent.name, &token, "message", &agent.name, "a fresh reply")
        .expect("send user notification message");
    let user_notification = sock
        .expect_frame_matching(
            |f| f["type"].as_str() == Some("user_notification") && f["agent"].as_str() == Some(agent.name.as_str()),
            USER_NOTIFICATION_TIMEOUT,
        )
        .await
        .expect("a user_notification delta for the user notification");
    assert_eq!(user_notification["kind"].as_str(), Some("message"), "carries the kind");
    assert_eq!(user_notification["title"].as_str(), Some(agent.name.as_str()), "carries the title");
    assert_eq!(user_notification["body"].as_str(), Some("a fresh reply"), "carries the body");

    // The kind is a closed set: an unknown kind is rejected with 400 (mapped to the error string).
    let err = c
        .send_user_notification(&agent.name, &token, "bogus", &agent.name, "nope")
        .expect_err("an unknown kind is rejected");
    assert!(err.contains("unknown user notification kind"), "unexpected error for a bad kind: {err}");
    sock.close().await.ok();
}

/// The user-notification feed's seen watermark is synced state on the gateway branch:
/// `POST /notifications/seen` advances it server-side and every `/sync` session receives a `state`
/// delta carrying the new `userNotificationsSeenAt`; an appended notification moves
/// `lastUserNotificationAt` the same way. Predicates are `>=` because parallel scenarios share the
/// server and may append or mark concurrently.
#[tokio::test]
async fn marking_the_feed_seen_projects_the_watermark_on_the_gateway_branch() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-seen");
    let token = c.read_agent_token(&agent.name).expect("read agent token");

    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    let seen_at = c.mark_notifications_seen().expect("mark notifications seen");
    assert!(seen_at > 0, "the watermark is the server's now");
    sock.expect_frame_matching(
        |f| {
            f["type"].as_str() == Some("state")
                && f["value"]["userNotificationsSeenAt"].as_u64().is_some_and(|at| at >= seen_at)
        },
        USER_NOTIFICATION_TIMEOUT,
    )
    .await
    .expect("a state delta carrying the advanced seen watermark");

    c.send_user_notification(&agent.name, &token, "message", &agent.name, "past the watermark")
        .expect("send user notification");
    sock.expect_frame_matching(
        |f| {
            f["type"].as_str() == Some("state")
                && f["value"]["lastUserNotificationAt"].as_u64().is_some_and(|at| at >= seen_at)
        },
        USER_NOTIFICATION_TIMEOUT,
    )
    .await
    .expect("a state delta carrying the newest entry's stamp");
    sock.close().await.ok();
}

/// (3) `POST /app-chat/message` with an explicit intent id round-trips end-to-end: the echo on the
/// replay-free chat socket carries the SAME `intent_id` the HTTP intake was given (the delivery-truth
/// contract clients dedup and confirm on), and `GET /app-chat/history` then returns that message.
#[tokio::test]
async fn send_message_intent_id_echoes_on_the_chat_socket() {
    let c = SERVER.client();
    let agent = running_agent(&c, "chat-intent");
    let mut chat = open_chat_socket(&c, &agent.name).await;

    let (intent, echo) = drive_and_expect_echo(&c, &mut chat, &agent.name, "carry my intent").await;
    assert_eq!(
        echo["intent_id"].as_str(),
        Some(intent.as_str()),
        "the chat-socket echo carries the exact intent id the send was given"
    );
    assert!(echo.get("id").is_some(), "the echoed event carries an id");

    // The durable copy is in the store: history returns the same message keyed by its intent id.
    let history = c.fetch_app_chat_history(&agent.name, 50).expect("fetch history");
    let events = history["events"].as_array().expect("history events array");
    assert!(
        events.iter().any(|e| e["intent_id"].as_str() == Some(intent.as_str())),
        "history returns the sent message carrying {intent}: {history}"
    );
    chat.close().await.ok();
}

/// (4, D3) A garbage `reauth` on a raw-key socket closes it; a valid `reauth` on a JWT socket keeps
/// it open and still delivers a subsequent `user_notification` (the liveness probe).
#[tokio::test]
async fn reauth_extends_and_closes_on_bad() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-reauth");
    let token = c.read_agent_token(&agent.name).expect("read agent token");

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

    // (b) JWT socket + a valid reauth -> stays open and still fans a subsequent user notification.
    let jwt = c.mint_access_token().expect("mint jwt");
    let mut tok = c.open_sync_with_token(&jwt.access_token).await.expect("open jwt sync");
    handshake(&mut tok).await;
    let fresh = c.mint_access_token().expect("mint fresh jwt");
    tok.reauth(&fresh.access_token).await.expect("send valid reauth");
    send_user_notification_and_expect_delta(&c, &mut tok, &agent.name, &token, "after reauth").await;
    tok.close().await.ok();
}

/// (5) Unknown/malformed client frames are ignored; a following user notification still fans its
/// delta, proving the socket stayed live.
#[tokio::test]
async fn unknown_client_frames_are_ignored() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-unknown");
    let token = c.read_agent_token(&agent.name).expect("read agent token");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    // An unknown `type` and a non-object frame both fail ClientFrame parsing and are dropped.
    sock.send_client_frame(&serde_json::json!({ "type": "future", "x": 1 }))
        .await
        .expect("send unknown frame");
    sock.send_client_frame(&serde_json::json!("garbage-not-a-frame"))
        .await
        .expect("send malformed frame");

    // The socket stayed live: a following user notification still fans its delta here.
    send_user_notification_and_expect_delta(&c, &mut sock, &agent.name, &token, "still alive").await;
    sock.close().await.ok();
}

/// (6) A device's reported context reaches the store, the roster, the agent, and the agent's read
/// path. A `client_context` frame carrying `timezone` + `position` from a focused device fans a
/// `devices` delta with those facts; the agent's `GET /agents/{name}/devices` (X-Agent-Token) returns
/// them; and vestad drops a `user-timezone` notification into an agent whose own zone differs (a
/// fresh agent runs on UTC). The HTTP carrier `PUT /devices/{id}/context` lands in the same store.
#[tokio::test]
async fn device_context_reaches_roster_agent_and_notification_intake() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-context");
    let token = c.read_agent_token(&agent.name).expect("read agent token");
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    let device_id = format!("dev-{}", agent.name);
    sock.send_client_frame(&serde_json::json!({
        "type": "client_context", "focused": true, "client": "mobile",
        "deviceId": device_id, "descriptor": "Vesta Mobile on iOS",
        "timezone": "Asia/Tokyo",
        "position": {"latitude": 35.6762, "longitude": 139.6503, "accuracyM": 50.0,
                     "place": {"city": "Tokyo", "country": "Japan"}},
    }))
    .await
    .expect("send client_context with device context");
    let devices = sock
        .expect_frame_matching(
            |f| {
                f["type"].as_str() == Some("devices")
                    && f["devices"].as_array().is_some_and(|list| {
                        list.iter().any(|d| d["id"].as_str() == Some(device_id.as_str()) && d["timezone"].is_string())
                    })
            },
            USER_NOTIFICATION_TIMEOUT,
        )
        .await
        .expect("a devices delta carrying the reported context");
    let device = devices["devices"]
        .as_array()
        .and_then(|list| list.iter().find(|d| d["id"].as_str() == Some(device_id.as_str())))
        .expect("the reporting device");
    assert_eq!(device["timezone"].as_str(), Some("Asia/Tokyo"));
    assert_eq!(device["position"]["place"]["city"].as_str(), Some("Tokyo"));

    // The agent reads the same facts through its own self-scoped route.
    let seen = c.agent_devices(&agent.name, &token).expect("agent devices");
    let mine = seen["devices"]
        .as_array()
        .and_then(|list| list.iter().find(|d| d["id"].as_str() == Some(device_id.as_str())))
        .expect("the device on the agent's read path");
    assert_eq!(mine["timezone"].as_str(), Some("Asia/Tokyo"));
    assert_eq!(mine["position"]["latitude"].as_f64(), Some(35.6762));

    // A fresh agent runs on UTC, so Tokyo is news: the notification lands in its intake. A model-less
    // agent never consumes it, so it stays for the poll.
    let container = vesta_tests::agent_container_name(&agent.name);
    let deadline = Instant::now() + USER_NOTIFICATION_TIMEOUT;
    let listing = loop {
        let listing = vesta_tests::exec_in_container(&container, "ls /root/agent/notifications").unwrap_or_default();
        if listing.contains("user-timezone-") && listing.contains("user-location-") {
            break listing;
        }
        assert!(Instant::now() < deadline, "no user-timezone/user-location notification landed; intake: {listing}");
        tokio::time::sleep(Duration::from_millis(500)).await;
    };
    let payload = vesta_tests::exec_in_container(
        &container,
        "cat /root/agent/notifications/user-timezone-*.json",
    )
    .expect("read the timezone notification");
    assert!(payload.contains("\"source\":\"vestad\"") && payload.contains("Asia/Tokyo"), "payload: {payload}, intake: {listing}");

    // The HTTP carrier writes the same store: a later zone shows on the agent's read path.
    c.report_device_context(&device_id, &serde_json::json!({ "timezone": "Europe/Paris" }))
        .expect("report context over http");
    let seen = c.agent_devices(&agent.name, &token).expect("agent devices after http report");
    let mine = seen["devices"]
        .as_array()
        .and_then(|list| list.iter().find(|d| d["id"].as_str() == Some(device_id.as_str())))
        .expect("the device on the agent's read path");
    assert_eq!(mine["timezone"].as_str(), Some("Europe/Paris"));
    assert_eq!(mine["position"]["place"]["city"].as_str(), Some("Tokyo"), "a zone-only report keeps the position");
    sock.close().await.ok();
}
