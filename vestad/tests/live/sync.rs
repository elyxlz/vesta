//! Live room-socket e2e against a REAL, settled Claude agent (release-gated tier). Bridges the two
//! halves the fake-token server suite (`tests/server/sync.rs`) can only test apart: a post into the
//! agent's direct room carrying an `intent_id` echoes that id back on `/rooms/ws` (the
//! delivery-truth contract), AND the real model round-trip that follows streams a genuine agent
//! reply (a `chat` message the skill's `chat send` posts to the node) onto the same socket. Skips
//! with no `CLAUDE_CREDENTIALS` (the pool is unprovisioned, so the lock returns None), matching
//! every other live test.

use std::time::{Duration, Instant};

use vesta_tests::client::direct_room;
use vesta_tests::SERVER;

use super::common::lock_live_agent_a;

/// The node echoes a post the moment it appends it, so the echo lands fast. The bounded resends
/// close the one race left: the room socket's subscriber may register a hair after the first echo
/// was fanned, and the socket is replay-free, so a missed echo needs another post with a fresh id.
const ECHO_TIMEOUT: Duration = Duration::from_secs(45);
const ECHO_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(4);
/// A full real-model round-trip: the chat notification is delivered, the SDK query runs, and the
/// agent's reply arrives as a `chat` message on the socket. Generous like the first-start settle
/// budget; it only has to not be hit in practice.
const REPLY_TIMEOUT: Duration = Duration::from_secs(300);

/// True when `frame` is the user echo carrying our `intent`. Only an intake message carries an
/// `intent_id`, and the room-level frames carry no `type` of `user` at all.
fn is_echo(frame: &serde_json::Value, intent: &str) -> bool {
    frame["type"].as_str() == Some("user") && frame["intent_id"].as_str() == Some(intent)
}

/// True when `frame` is a non-empty agent reply (`chat`): the real model's response the skill
/// posted to the node, not the user echo and not a room-level frame.
fn is_agent_reply(frame: &serde_json::Value) -> bool {
    frame["type"].as_str() == Some("chat")
        && frame["text"].as_str().is_some_and(|text| !text.trim().is_empty())
}

/// End-to-end: open the room socket for a real settled agent's direct room, post one message with
/// an intent id, observe the echo carrying that id, then observe the real agent reply arriving on
/// the same socket. No-ops (returns) without `CLAUDE_CREDENTIALS`.
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
    let mut chat = c
        .open_rooms_socket(Some(&direct_room(&name)))
        .await
        .expect("open the agent's room socket");

    let text = "Please reply with a short one-line greeting.";

    // Repost on a bounded cadence with a fresh intent each attempt until the node's echo lands,
    // closing the subscriber-registration race (a duplicate intent is deduped, so each attempt
    // carries a new id). Once an echo is in hand the socket is proven subscribed, so the later
    // reply needs no repost.
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
            "no user-echo carrying an intent on the room socket within {ECHO_TIMEOUT:?}"
        );
        attempt += 1;
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    // The real model round-trip: the agent's `chat send` reply posts a non-empty `chat` message
    // the node fans onto the same socket.
    chat.expect_frame_matching(is_agent_reply, REPLY_TIMEOUT)
        .await
        .expect("a real agent reply on the room socket within the round-trip budget");

    chat.close().await.ok();
}
