//! `/sync` WebSocket integration scenarios, driven end-to-end against a real vestad + agent
//! container through the T1 harness `SyncSocket`. The state plane carries roster + snapshot + pending
//! notifications + `reauth` + the always-on `user_notification` delta; it no longer transports chat.
//! Chat lives on vestad's own chat node: intake is `POST /rooms/{id}/messages` and the live edge is
//! the replay-free `/rooms/ws`, so the chat scenario here drives those. What it adds over
//! `chat_rooms.rs`, which needs nothing running in a container, is the container itself: the skill's
//! daemon replicates a node message into the agent's notification intake, and `chat send` posts the
//! agent's answer back through that daemon. User notifications (a rate limit, a status change) come
//! from the agent-side user-notification primitive looped back through vestad
//! (`POST /agents/{name}/user-notification`, `X-Agent-Token`), which fans a `user_notification` delta
//! to every connected session; the user-notification scenario exercises that path and the
//! closed-kind 400, and the reauth/unknown scenarios reuse it as a liveness probe.
//!
//! Fake-token agents settle unprovisioned and run no model, and never run the skill's setup, so the
//! chat scenario installs the CLI and starts the daemon by hand (`start_chat_daemon`, docker exec).
//! The reply it asserts is the agent's own `chat send`, so no real model is needed; the real-model
//! round trip is the live tier's (`tests/live/sync.rs`).
//!
//! Two spec sub-scenarios are deliberately absent: below-window client rejection (D2, dropped, since
//! the server never rejects; the served version window is a client-side gate) and the reauth
//! deadline-expiry timer (D3, covered in the handler unit tier via `token_deadline`/`expire`).
//! This module owns the socket-observable behaviors only.

use std::time::{Duration, Instant};

use vesta_tests::client::{direct_room, Client, SyncSocket};
use vesta_tests::{
    agent_container_name, exec_in_container, inject_fake_token, unique_agent, TestAgent, SERVER,
    SHARED_RO_AGENT,
};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 90;
const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
/// Budget for the daemon's replica to turn a node message into a notification file in the intake.
const REPLICA_NOTIFICATION_TIMEOUT: Duration = Duration::from_secs(60);
/// Budget for `chat send` to reach the node through a daemon that may still be dialing it.
const AGENT_SEND_TIMEOUT: Duration = Duration::from_secs(60);
/// Budget for an already-subscribed room session to receive one expected frame.
const FRAME_TIMEOUT: Duration = Duration::from_secs(30);
const POLL_INTERVAL: Duration = Duration::from_millis(500);
/// Budget for a user notification to fan its `user_notification` delta to a connected session (loopback POST -> broadcast).
const USER_NOTIFICATION_TIMEOUT: Duration = Duration::from_secs(20);
/// How long to poll (via reconnect) for a fresh agent to surface in a snapshot.
const SNAPSHOT_POLL_TIMEOUT: Duration = Duration::from_secs(30);

// D2: the served compatibility window's low end, mirrored from vestad's crate-private
// `sync::MIN_SUPPORTED_CLIENT_VERSION` (not importable from an integration crate, so pinned to the
// contract literal here). Stage 4 of the chat rooms epic moved the chat contract from the proxy
// onto rooms, a break for shipped clients, so the floor moved to the in-gap bump above the shipped
// version (see release.sh for the in-gap bump convention).
const EXPECT_MIN_SUPPORTED: &str = "0.3.5";

/// Create a fake-token agent and bring it up to a live tap. Fake-token agents settle at
/// `unprovisioned`/`not_authenticated`, enough to exercise frame plumbing (no real model needed).
/// The chat skill is not part of that: the one scenario that needs it starts its daemon itself.
fn running_agent<'a>(c: &'a Client, prefix: &str) -> TestAgent<'a> {
    let agent = TestAgent::create(c, &unique_agent(prefix)).expect("create agent");
    inject_fake_token(c, &agent.name);
    c.start_agent(&agent.name).expect("start agent");
    c.wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running");
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

/// Wait for the skill's replica to write `text` into the agent's notification intake. A model-less
/// agent defers every message while it is unauthenticated and keeps the file, so the notification
/// stays on disk for the poll. Bounded, never a bare sleep.
async fn expect_notification_in_intake(container: &str, text: &str) {
    let deadline = Instant::now() + REPLICA_NOTIFICATION_TIMEOUT;
    loop {
        let intake = exec_in_container(
            container,
            "cat /root/agent/notifications/*-chat-message.json 2>/dev/null || true",
        )
        .unwrap_or_default();
        if intake.contains(text) {
            return;
        }
        assert!(
            Instant::now() < deadline,
            "the replica never wrote {text:?} into the agent's intake within {REPLICA_NOTIFICATION_TIMEOUT:?}: {intake}"
        );
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

/// Answer as the agent does, from inside its container: `chat send` hands the reply to the daemon,
/// which posts it to the node. Retried while the daemon's replica is still dialing the node (a send
/// before it answers reports the node unreachable rather than posting).
async fn agent_replies(container: &str, text: &str) {
    let deadline = Instant::now() + AGENT_SEND_TIMEOUT;
    loop {
        let sent = exec_in_container(
            container,
            &format!(". /run/vestad-env && chat send -m '{text}'"),
        );
        match &sent {
            Ok(answer) if answer.contains("\"ok\": true") => return,
            _ => assert!(
                Instant::now() < deadline,
                "`chat send` never reached the node within {AGENT_SEND_TIMEOUT:?}: {sent:?}"
            ),
        }
        tokio::time::sleep(POLL_INTERVAL).await;
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
/// `X-Agent-Token` fans a `user_notification` delta `{id,at,agent,kind,title,body}` to a connected `/sync`
/// session (the loopback path the chat reply hook and the rate-limit notice use). The kind is a
/// closed set: an unknown kind is a 400.
#[tokio::test]
async fn user_notification_message_fans_a_delta_and_rejects_unknown_kinds() {
    let c = SERVER.client();
    let agent = running_agent(&c, "sync-notify");
    let token = c.read_agent_token(&agent.name).expect("read agent token");

    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;

    // A valid user notification (kind message, the chat reply hook's shape) fans a delta carrying
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
    assert!(user_notification["id"].as_u64().is_some(), "carries the log entry's id");
    assert!(user_notification["at"].as_u64().is_some(), "carries the log entry's stamp");
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

/// (3) A message the user posts to the node reaches the agent in its container, and the agent's own
/// answer comes back on the same room socket. The post echoes as a `user` frame carrying the SAME
/// `intent_id` the intake was given (the delivery-truth contract clients dedup and confirm on); the
/// skill's replica turns it into a notification in the agent's intake; `chat send` from inside the
/// container arrives as a `chat` frame from that agent; and history then holds both, oldest first.
/// Room-level frames (`room_created`, `room_deleted`, `user_finished_talking`) may interleave on the
/// socket, so every read here matches on what it wants rather than on frame order.
#[tokio::test]
async fn a_post_reaches_the_agent_and_its_reply_comes_back_on_the_room_socket() {
    let c = SERVER.client();
    let agent = running_agent(&c, "chat-intent");
    c.start_chat_daemon(&agent.name).expect("start chat daemon");
    let container = agent_container_name(&agent.name);
    let room = direct_room(&agent.name);
    let mut sock = c
        .open_rooms_socket(Some(&room))
        .await
        .expect("open the room socket");

    let (intent, echo) = c
        .drive_until_echo(&mut sock, &room, "chat-intent")
        .await
        .expect("a user post echoes on the room socket");
    assert_eq!(
        echo["type"].as_str(),
        Some("user"),
        "a user post is a user message"
    );
    assert_eq!(
        echo["intent_id"].as_str(),
        Some(intent.as_str()),
        "the echo carries the exact intent id the post was given"
    );
    let posted_id = echo["id"]
        .as_u64()
        .expect("the echoed message carries an id");
    let posted_text = echo["text"]
        .as_str()
        .expect("the echoed message carries its text")
        .to_string();

    expect_notification_in_intake(&container, &posted_text).await;

    let reply = "the answer from inside the container";
    agent_replies(&container, reply).await;
    let frame = sock
        .expect_frame_matching(
            |f| f["sender"].as_str() == Some(agent.name.as_str()),
            FRAME_TIMEOUT,
        )
        .await
        .expect("the agent's reply on the room socket");
    assert_eq!(
        frame["type"].as_str(),
        Some("chat"),
        "an agent post is a chat message"
    );
    assert_eq!(frame["text"].as_str(), Some(reply));
    let reply_id = frame["id"].as_u64().expect("the reply carries an id");

    // The durable copy is the node's: one page holds both messages, the post before the answer.
    let history = c
        .fetch_chat_history(&agent.name, 50)
        .expect("fetch the room history");
    let events = history["events"].as_array().expect("history events array");
    let position = |id: u64| events.iter().position(|e| e["id"].as_u64() == Some(id));
    let posted_at =
        position(posted_id).unwrap_or_else(|| panic!("history holds the user post: {history}"));
    let replied_at =
        position(reply_id).unwrap_or_else(|| panic!("history holds the agent reply: {history}"));
    assert!(
        posted_at < replied_at,
        "history returns the post before the reply: {history}"
    );
    assert_eq!(
        events[posted_at]["intent_id"].as_str(),
        Some(intent.as_str()),
        "the stored post keeps its intent id"
    );
    sock.close().await.ok();
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
