//! Live `/sync` e2e against a REAL, settled Claude agent (release-gated tier). Bridges the two
//! halves the fake-token server suite (`tests/server/sync.rs`) can only test apart: an app-chat
//! `send_message` carrying an `intent_id` echoes that id back on the watch (the delivery-truth
//! contract), AND the real model round-trip that follows streams a genuine `assistant` text event
//! onto the same watch. Skips with no `CLAUDE_CREDENTIALS` (the pool is unprovisioned, so the lock
//! returns None), matching every other live test.

use std::time::{Duration, Instant};

use vesta_tests::client::SyncSocket;
use vesta_tests::SERVER;

use super::common::lock_live_agent_a;

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(20);
/// The user echo is written in-process the instant the send is relayed, so it lands fast. The
/// bounded resends only close the watch-subscribe race: the watch frame may reach vestad a hair
/// after the first echo was broadcast, and the live edge never replays, so a lost echo needs
/// another send, not a longer read.
const ECHO_TIMEOUT: Duration = Duration::from_secs(45);
const ECHO_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(4);
/// A full real-model round-trip: the app-chat notification is delivered, the SDK query runs, and
/// the assistant text streams back. Generous like the first-start settle budget; it only has to
/// not be hit in practice.
const ASSISTANT_TIMEOUT: Duration = Duration::from_secs(300);

/// Read the mandatory hello then the immediate snapshot (deterministically frames 1 and 2 before
/// the handler enters its select loop). Contract details are asserted in the server suite; here we
/// only need past the handshake to the watch.
async fn handshake(sock: &mut SyncSocket) {
    let hello = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("hello frame");
    assert_eq!(hello["type"].as_str(), Some("hello"), "first frame is hello");
    let snapshot = sock.recv_frame(HANDSHAKE_TIMEOUT).await.expect("snapshot frame");
    assert_eq!(snapshot["type"].as_str(), Some("snapshot"), "second frame is snapshot");
}

/// True when `frame` is an `append` for `agent` carrying the user-echo event with our `intent`.
fn is_echo(frame: &serde_json::Value, agent: &str, intent: &str) -> bool {
    frame["type"].as_str() == Some("append")
        && frame["agent"].as_str() == Some(agent)
        && frame["events"].as_array().is_some_and(|events| {
            events
                .iter()
                .any(|e| e["type"].as_str() == Some("user") && e["intent_id"].as_str() == Some(intent))
        })
}

/// True when `frame` is an `append` for `agent` carrying a non-empty `assistant` text event: the
/// real model's response, not the in-process user echo.
fn is_assistant_text(frame: &serde_json::Value, agent: &str) -> bool {
    frame["type"].as_str() == Some("append")
        && frame["agent"].as_str() == Some(agent)
        && frame["events"].as_array().is_some_and(|events| {
            events.iter().any(|e| {
                e["type"].as_str() == Some("assistant")
                    && e["text"].as_str().is_some_and(|text| !text.trim().is_empty())
            })
        })
}

/// End-to-end: connect `/sync`, watch a real settled agent, send one app-chat message with an
/// intent id, observe the echo append carrying that id, then observe the real assistant response
/// event arriving on the same watch. No-ops (returns) without `CLAUDE_CREDENTIALS`.
#[tokio::test]
async fn live_send_echoes_intent_then_streams_a_real_assistant_response() {
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
    let mut sock = c.open_sync().await.expect("open sync");
    handshake(&mut sock).await;
    sock.watch(&name).await.expect("watch the live agent");

    let intent = "i-live-sync-e2e";
    let text = "Please reply with a short one-line greeting.";

    // Resend on a bounded cadence until the in-process echo lands, closing the watch-subscribe
    // race. Once the echo is in hand the watch is proven subscribed, so the later assistant event
    // needs no resend.
    let echo_deadline = Instant::now() + ECHO_TIMEOUT;
    loop {
        let _ = c.send_message(&name, text, Some(intent));
        if sock
            .expect_frame_matching(|f| is_echo(f, &name, intent), ECHO_ATTEMPT_TIMEOUT)
            .await
            .is_ok()
        {
            break;
        }
        assert!(
            Instant::now() < echo_deadline,
            "no user-echo append carrying {intent} within {ECHO_TIMEOUT:?}"
        );
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    // The real model round-trip streams a genuine assistant text event onto the same watch.
    sock.expect_frame_matching(|f| is_assistant_text(f, &name), ASSISTANT_TIMEOUT)
        .await
        .expect("a real assistant response event on the watch within the round-trip budget");

    sock.close().await.ok();
}
