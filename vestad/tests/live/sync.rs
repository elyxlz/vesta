//! Live chat-socket e2e against a REAL, settled Claude agent (release-gated tier). Bridges the two
//! halves the fake-token server suite (`tests/server/sync.rs`) can only test apart: an app-chat
//! `send_message` carrying an `intent_id` echoes that id back on the chat socket (the delivery-truth
//! contract), AND the real model round-trip that follows streams a genuine agent reply (a `chat`
//! event the skill's `app-chat send` persists and fans) onto the same socket. Skips with no
//! `CLAUDE_CREDENTIALS` (the pool is unprovisioned, so the lock returns None), matching every other
//! live test.

use std::time::{Duration, Instant};

use vesta_tests::client::{Client, SyncSocket};
use vesta_tests::SERVER;

use super::common::lock_live_agent_a;

/// The app-chat daemon writes the user echo the instant it intakes the send, so it lands fast. The
/// bounded resends close two races: the chat socket's subscriber may register a hair after the first
/// echo was fanned (the socket is replay-free, so a missed echo needs another send with a fresh id),
/// and a real agent's daemon may still be coming up on the first send (the send 502s and retries).
const ECHO_TIMEOUT: Duration = Duration::from_secs(45);
const ECHO_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(4);
/// The proxy 404s the chat-socket upgrade until the daemon's service is registered, so the open is
/// retried briefly over this window (a settled pool agent's daemon is normally already up).
const CHAT_SOCKET_OPEN_TIMEOUT: Duration = Duration::from_secs(30);
/// A full real-model round-trip: the app-chat notification is delivered, the SDK query runs, and the
/// agent's reply streams back as a `chat` event on the socket. Generous like the first-start settle
/// budget; it only has to not be hit in practice.
const REPLY_TIMEOUT: Duration = Duration::from_secs(300);

/// True when `frame` is the app-chat user echo carrying our `intent` (a `StoredEvent` on the chat
/// socket, no envelope). Only the intake event carries an `intent_id`.
fn is_echo(frame: &serde_json::Value, intent: &str) -> bool {
    frame["type"].as_str() == Some("user") && frame["intent_id"].as_str() == Some(intent)
}

/// True when `frame` is a non-empty agent reply (`chat`): the real model's response the skill
/// persisted and fanned on its socket, not the user echo.
fn is_agent_reply(frame: &serde_json::Value) -> bool {
    frame["type"].as_str() == Some("chat")
        && frame["text"].as_str().is_some_and(|text| !text.trim().is_empty())
}

/// Open the live agent's app-chat chat socket, retrying briefly past a still-registering service.
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

/// End-to-end: open the app-chat chat socket for a real settled agent, send one message with an intent
/// id, observe the echo carrying that id, then observe the real agent reply arriving on the same
/// socket. No-ops (returns) without `CLAUDE_CREDENTIALS`.
#[tokio::test]
async fn live_send_echoes_intent_then_streams_a_real_agent_reply() {
    let Some((shared, _container)) = lock_live_agent_a() else {
        return;
    };
    let name = shared
        .as_ref()
        .expect("pool agent present when the lock returned a container")
        .0
        .name
        .clone();

    let c = SERVER.client();
    let mut chat = open_chat_socket(&c, &name).await;

    let text = "Please reply with a short one-line greeting.";

    // Resend on a bounded cadence with a fresh intent each attempt until the daemon's echo lands,
    // closing the subscriber-registration and daemon-warmup races (a duplicate intent is deduped, so
    // each attempt carries a new id). Once an echo is in hand the socket is proven subscribed, so the
    // later reply needs no resend.
    let echo_deadline = Instant::now() + ECHO_TIMEOUT;
    let mut attempt = 0u32;
    loop {
        let intent = format!("i-live-chat-e2e-{attempt}");
        let _ = c.send_message(&name, text, Some(&intent));
        if chat
            .expect_frame_matching(|f| is_echo(f, &intent), ECHO_ATTEMPT_TIMEOUT)
            .await
            .is_ok()
        {
            break;
        }
        assert!(
            Instant::now() < echo_deadline,
            "no user-echo carrying an intent on the chat socket within {ECHO_TIMEOUT:?}"
        );
        attempt += 1;
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    // The real model round-trip: the agent's `app-chat send` reply streams a non-empty `chat` event
    // onto the same socket.
    chat.expect_frame_matching(is_agent_reply, REPLY_TIMEOUT)
        .await
        .expect("a real agent reply event on the chat socket within the round-trip budget");

    chat.close().await.ok();
}
