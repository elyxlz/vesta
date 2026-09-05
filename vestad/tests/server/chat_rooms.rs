//! The chat node end to end: the rooms every agent gets, the rooms the user and an agent open,
//! intake and its echo on `/rooms/ws`, paged history, the speaking and burst gates, history
//! import, and the rename/delete hooks, all driven against a real vestad through the harness.
//! Attachments ride along: the chunked upload and its offset refusal, the metadata a finalized id
//! carries onto a message, what a browser is told about a served blob, and the refusal a post
//! naming an unknown id gets.
//!
//! Nothing here needs anything running inside a container: no docker exec, no wait for an agent
//! to boot. `POST /agents` mints the direct room before it answers, the chat gate resolves an
//! agent token from the env file vestad wrote on the host, and every route under test is vestad's
//! own, so `TestAgent::create` (which does create and start a container) is the whole fixture.
//!
//! Two behaviors of the live edge stay out of reach here, and are covered by the node's own tests:
//! the bounded socket send (a client that stops reading is abandoned after the send timeout) and
//! the lag close (a session that falls behind the broadcast depth is closed so its client reseeds).
//! Both need a socket peer that stops reading for longer than this suite's budgets allow.
//!
//! `GET /rooms` is gateway-wide and this target runs its scenarios in parallel against one shared
//! server, so every room-list assertion is containment over ids this scenario made, never
//! equality. The `server` target as a whole is the Docker gate (`check.sh integration` runs it
//! without `--ignored`), which is why these carry no `#[ignore]`, exactly like their siblings.

use std::time::{Duration, Instant};

use vesta_tests::client::{Client, SyncSocket};
use vesta_tests::{unique_agent, ProxyAuth, TestAgent, SERVER};

/// Budget for a fresh room-socket session to be subscribed and echo a post back.
const SOCKET_READY_TIMEOUT: Duration = Duration::from_secs(30);
/// Per-attempt read window inside the readiness drive.
const ECHO_ATTEMPT_TIMEOUT: Duration = Duration::from_secs(3);
/// Budget for an already-subscribed session to receive one expected frame.
const FRAME_TIMEOUT: Duration = Duration::from_secs(15);
/// Budget for an agent message's user notification to reach the durable feed.
const NOTIFICATION_TIMEOUT: Duration = Duration::from_secs(15);
const POLL_INTERVAL: Duration = Duration::from_millis(200);
/// The newest-first window `GET /notifications` is read over; the route's own cap.
const NOTIFICATION_PAGE_LIMIT: usize = 200;

/// The node's refusal texts, mirrored from the crate-private `chat::{SPEAKING_REFUSAL,
/// BURST_REFUSAL}` (an integration crate cannot import them). The agent reads these as its
/// instruction, so they are contract, not phrasing.
const SPEAKING_REFUSAL: &str =
    "the user is talking right now: drop this reply, wait for their next message, then answer the whole thought";
const BURST_REFUSAL: &str =
    "burst guard: this room holds 40 agent messages since the user last spoke; stop until the user writes again";
/// Agent messages a room holds since the user's last one before intake refuses, from `chat::ROOM_AGENT_POSTS_WITHOUT_USER`.
const BURST_CAP: usize = 40;
/// Posts the speaking-gate drive may make before it gives up. Under the burst cap on purpose, so a
/// gate that never binds fails as itself rather than as the other guard.
const GATE_ATTEMPTS: usize = BURST_CAP / 2;

/// The attachment surface, rooted at the gateway like every other room route.
const ATTACHMENTS_PATH: &str = "/rooms/attachments";
/// A well-formed id no session ever minted, for the refusal a post gets naming one.
const UNKNOWN_ATTACHMENT_ID: &str = "00112233445566778899aabbccddeeff";
/// The eight bytes every PNG opens with. Nothing sniffs the blob, so this is only a body that
/// reads as what it claims to be.
const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";

// ── fixtures ────────────────────────────────────────────────────

/// Create an agent for a chat scenario: the create answers only once its direct room exists.
fn chat_agent<'a>(client: &'a Client, prefix: &str) -> TestAgent<'a> {
    TestAgent::create(client, &unique_agent(prefix)).expect("create agent")
}

/// An agent's own `AGENT_TOKEN`, read from the env file vestad wrote on the host (`export
/// AGENT_TOKEN=...`). The chat gate resolves an agent from that same file, so the container never
/// has to run for a scenario to post as the agent.
fn agent_token(name: &str) -> String {
    let path = SERVER
        .home_path()
        .join(format!(".config/vesta/vestad/agents/{name}.env"));
    let content =
        std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    content
        .lines()
        .find_map(|line| {
            line.strip_prefix("export ")
                .unwrap_or(line)
                .strip_prefix("AGENT_TOKEN=")
        })
        .unwrap_or_else(|| panic!("no AGENT_TOKEN in {}", path.display()))
        .to_string()
}

fn parse(body: &str) -> serde_json::Value {
    serde_json::from_str(body).unwrap_or_else(|e| panic!("parse response body ({e}): {body}"))
}

fn direct_room(agent: &str) -> String {
    format!("dm:{agent}")
}

fn direct_room_path(agent: &str) -> String {
    format!("/rooms/{}", direct_room(agent))
}

// ── route wrappers ──────────────────────────────────────────────

fn list_rooms(client: &Client, auth: ProxyAuth) -> Vec<serde_json::Value> {
    let (status, raw) = client.proxy_get("/rooms", auth).expect("list rooms");
    assert_eq!(status, 200, "GET /rooms: {raw}");
    parse(&raw)["rooms"]
        .as_array()
        .unwrap_or_else(|| panic!("GET /rooms carries a rooms array: {raw}"))
        .clone()
}

fn room_ids(rooms: &[serde_json::Value]) -> Vec<String> {
    rooms
        .iter()
        .filter_map(|room| room["id"].as_str().map(str::to_string))
        .collect()
}

fn open_room(
    client: &Client,
    auth: ProxyAuth,
    body: &serde_json::Value,
) -> (u16, serde_json::Value) {
    let (status, raw) = client
        .proxy_post_json("/rooms", auth, body)
        .expect("open room");
    (status, parse(&raw))
}

fn post_message(
    client: &Client,
    room: &str,
    auth: ProxyAuth,
    body: &serde_json::Value,
) -> (u16, serde_json::Value) {
    let (status, raw) = client
        .proxy_post_json(&format!("/rooms/{room}/messages"), auth, body)
        .expect("post message");
    (status, parse(&raw))
}

/// Append one chunk of an upload at an explicit offset, preserving the status and body: the 409
/// an offset mismatch answers is the contract, not a failure.
fn put_chunk(client: &Client, id: &str, offset: u64, bytes: &[u8]) -> (u16, String) {
    client
        .proxy_put_bytes(
            &format!("{ATTACHMENTS_PATH}/{id}/data?offset={offset}"),
            ProxyAuth::ApiKey,
            bytes,
        )
        .expect("append an upload chunk")
}

fn attachment_status(client: &Client, id: &str) -> serde_json::Value {
    let (status, raw) = client
        .proxy_get(
            &format!("{ATTACHMENTS_PATH}/{id}/status"),
            ProxyAuth::ApiKey,
        )
        .expect("read the upload status");
    assert_eq!(status, 200, "GET {ATTACHMENTS_PATH}/{id}/status: {raw}");
    parse(&raw)
}

/// Stage one finalized attachment in a single chunk, answering its id. The chunked path is
/// scenario (10)'s subject; every other scenario only needs a blob that exists.
fn upload_attachment(client: &Client, name: &str, mime: &str, bytes: &[u8]) -> String {
    let (status, raw) = client
        .proxy_post_json(
            ATTACHMENTS_PATH,
            ProxyAuth::ApiKey,
            &serde_json::json!({ "name": name, "mime": mime, "size": bytes.len() }),
        )
        .expect("create the upload session");
    assert_eq!(status, 200, "POST {ATTACHMENTS_PATH}: {raw}");
    let id = parse(&raw)["id"]
        .as_str()
        .expect("the create answers an id")
        .to_string();
    let (status, raw) = put_chunk(client, &id, 0, bytes);
    assert_eq!(status, 200, "the whole blob lands in one chunk: {raw}");
    let (status, raw) = client
        .proxy_post_json(
            &format!("{ATTACHMENTS_PATH}/{id}/complete"),
            ProxyAuth::ApiKey,
            &serde_json::json!({}),
        )
        .expect("complete the upload");
    assert_eq!(status, 200, "the upload finalizes: {raw}");
    id
}

/// One response header as text, or `None` when it is absent or not text.
fn header(headers: &ureq::http::HeaderMap, name: &str) -> Option<String> {
    headers
        .get(name)
        .and_then(|value| value.to_str().ok())
        .map(str::to_string)
}

fn history(client: &Client, room: &str, query: &str) -> serde_json::Value {
    let (status, raw) = client
        .proxy_get(&format!("/rooms/{room}/history?{query}"), ProxyAuth::ApiKey)
        .expect("read history");
    assert_eq!(status, 200, "GET /rooms/{room}/history?{query}: {raw}");
    parse(&raw)
}

fn history_events(page: &serde_json::Value) -> Vec<serde_json::Value> {
    page["events"]
        .as_array()
        .unwrap_or_else(|| panic!("a history page carries an events array: {page}"))
        .clone()
}

/// The newest durable feed entry naming `agent` and carrying `body`, or `None` while the feed
/// holds none. Keyed on the body, not merely on position: vestad mints its own status entries for
/// every agent it observes, so the newest entry naming this one need not be the chat message.
fn feed_entry_for(client: &Client, agent: &str, body: &str) -> Option<serde_json::Value> {
    let (status, raw) = client
        .proxy_get(
            &format!("/notifications?limit={NOTIFICATION_PAGE_LIMIT}"),
            ProxyAuth::ApiKey,
        )
        .expect("list user notifications");
    assert_eq!(status, 200, "GET /notifications: {raw}");
    parse(&raw)["notifications"]
        .as_array()
        .unwrap_or_else(|| panic!("GET /notifications carries a notifications array: {raw}"))
        .iter()
        .find(|entry| {
            entry["agent"].as_str() == Some(agent) && entry["body"].as_str() == Some(body)
        })
        .cloned()
}

// ── socket drives ───────────────────────────────────────────────

/// Drive user posts into `room` until one echoes on `sock`, returning that post's intent id and
/// its echo. `/rooms/ws` is replay-free, so an event fanned before the session subscribed is gone:
/// a fresh intent per attempt is what closes the registration race, and the winning echo proves
/// the session is live for whatever the scenario asserts next.
async fn drive_until_echo(
    client: &Client,
    sock: &mut SyncSocket,
    room: &str,
    label: &str,
) -> (String, serde_json::Value) {
    let deadline = Instant::now() + SOCKET_READY_TIMEOUT;
    let mut attempt = 0u32;
    loop {
        let intent = format!("i-{label}-{attempt}");
        let body = serde_json::json!({ "text": format!("{label} {attempt}"), "intent_id": intent });
        let (status, answer) = post_message(client, room, ProxyAuth::ApiKey, &body);
        assert_eq!(status, 200, "user post into {room}: {answer}");
        if let Ok(frame) = sock
            .expect_frame_matching(
                |frame| frame["intent_id"].as_str() == Some(intent.as_str()),
                ECHO_ATTEMPT_TIMEOUT,
            )
            .await
        {
            return (intent, frame);
        }
        assert!(
            Instant::now() < deadline,
            "no room-socket echo for {room} within {SOCKET_READY_TIMEOUT:?}"
        );
        attempt += 1;
    }
}

// ── scenarios ───────────────────────────────────────────────────

/// (1) Every agent vestad knows has its direct room the moment it exists, and the user's room
/// list carries them.
#[test]
fn direct_rooms_exist_for_every_agent_and_the_user_lists_them() {
    let client = SERVER.client();
    let first = chat_agent(&client, "rooms-direct-a");
    let second = chat_agent(&client, "rooms-direct-b");

    let rooms = list_rooms(&client, ProxyAuth::ApiKey);
    let ids = room_ids(&rooms);
    assert!(
        ids.contains(&direct_room(&first.name)),
        "the room list carries {}: {ids:?}",
        direct_room(&first.name)
    );
    assert!(
        ids.contains(&direct_room(&second.name)),
        "the room list carries {}: {ids:?}",
        direct_room(&second.name)
    );

    let direct = rooms
        .iter()
        .find(|room| room["id"].as_str() == Some(&direct_room(&first.name)))
        .unwrap_or_else(|| panic!("the direct room of {}", first.name));
    assert_eq!(
        direct["name"],
        serde_json::Value::Null,
        "a direct room is unnamed"
    );
    assert_eq!(
        direct["agents"].as_array().map(Vec::len),
        Some(1),
        "a direct room holds its one agent: {direct}"
    );
    assert_eq!(direct["agents"][0].as_str(), Some(first.name.as_str()));

    // An agent sees only the rooms it is in, so the other agent's direct room is absent.
    let mine = room_ids(&list_rooms(
        &client,
        ProxyAuth::AgentToken(&agent_token(&first.name)),
    ));
    assert!(
        mine.contains(&direct_room(&first.name)),
        "an agent lists its own room: {mine:?}"
    );
    assert!(
        !mine.contains(&direct_room(&second.name)),
        "an agent never lists another agent's direct room: {mine:?}"
    );
}

/// (2) A named room is a fresh group; an unnamed pair is the one peer room, created once and
/// returned on every later open. An agent may only open a room it is in.
#[test]
fn the_user_opens_a_group_and_an_agent_opens_a_peer_room() {
    let client = SERVER.client();
    let first = chat_agent(&client, "rooms-open-a");
    let second = chat_agent(&client, "rooms-open-b");
    let pair = serde_json::json!([first.name, second.name]);

    let (status, body) = open_room(
        &client,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "name": "trip planning", "agents": pair }),
    );
    assert_eq!(status, 201, "a named room is created: {body}");
    let group = body["room"]["id"]
        .as_str()
        .expect("the group room carries an id");
    assert!(
        group.starts_with("grp-"),
        "a named room takes a group id: {group}"
    );
    assert_eq!(body["room"]["name"].as_str(), Some("trip planning"));

    // No name and exactly two agents is their peer room: created once, then returned as it is.
    let (status, body) = open_room(
        &client,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "agents": pair }),
    );
    assert_eq!(status, 201, "the peer room is created: {body}");
    let mut names = [first.name.as_str(), second.name.as_str()];
    names.sort_unstable();
    let peer = format!("dm:{}:{}", names[0], names[1]);
    assert_eq!(body["room"]["id"].as_str(), Some(peer.as_str()));

    let (status, body) = open_room(
        &client,
        ProxyAuth::AgentToken(&agent_token(&first.name)),
        &serde_json::json!({ "agents": pair }),
    );
    assert_eq!(
        status, 200,
        "opening the peer room again returns it: {body}"
    );
    assert_eq!(body["room"]["id"].as_str(), Some(peer.as_str()));

    // An agent that leaves itself out of the member set is refused before the node is asked.
    let (status, body) = open_room(
        &client,
        ProxyAuth::AgentToken(&agent_token(&first.name)),
        &serde_json::json!({ "agents": [second.name] }),
    );
    assert_eq!(
        status, 403,
        "an agent may not open a room it is not in: {body}"
    );
    assert_eq!(
        body["error"].as_str(),
        Some("an agent may only open rooms it is in")
    );
}

/// (3) A user post echoes on the room socket carrying the intent id it was given, a repeat of that
/// id is deduped instead of landing twice, and both history walks return the message.
#[tokio::test]
async fn a_user_post_echoes_on_the_room_socket_and_pages_back_by_id() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-echo");
    let room = direct_room(&agent.name);
    let mut sock = client
        .open_rooms_socket(Some(&room))
        .await
        .expect("open the room socket");

    let (intent, echo) = drive_until_echo(&client, &mut sock, &room, "echo").await;
    assert_eq!(
        echo["intent_id"].as_str(),
        Some(intent.as_str()),
        "the echo carries the exact intent id the post was given"
    );
    assert_eq!(
        echo["sender"].as_str(),
        Some("user"),
        "a user post is sent by the user"
    );
    assert_eq!(
        echo["type"].as_str(),
        Some("user"),
        "a user post is a user message"
    );
    assert_eq!(echo["room"].as_str(), Some(room.as_str()));
    let id = echo["id"]
        .as_u64()
        .expect("the echoed message carries an id");

    // The same intent id again is the client's retry: deduped, never a second message.
    let (status, answer) = post_message(
        &client,
        &room,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "text": "the retry", "intent_id": intent }),
    );
    assert_eq!(status, 200, "a retry answers 200: {answer}");
    assert_eq!(
        answer["deduped"].as_bool(),
        Some(true),
        "a retry is deduped: {answer}"
    );

    let newest = history(&client, &room, "limit=1");
    let events = history_events(&newest);
    assert_eq!(events.len(), 1, "limit=1 returns one message: {newest}");
    assert_eq!(
        events[0]["id"].as_u64(),
        Some(id),
        "the newest message is the one echoed"
    );
    assert_eq!(events[0]["intent_id"].as_str(), Some(intent.as_str()));

    // The replication walk from the start of the room returns it too.
    let walk = history(&client, &room, "after=0");
    assert!(
        history_events(&walk)
            .iter()
            .any(|event| event["id"].as_u64() == Some(id)),
        "the after=0 walk returns the message: {walk}"
    );
    sock.close().await.ok();
}

/// (4) An agent's post reaches the user's room socket as a `chat` message from that agent, and
/// mints one `message` entry in the durable user-notification feed.
#[tokio::test]
async fn an_agent_post_reaches_the_user_socket_and_mints_a_message_notification() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-agent-post");
    let token = agent_token(&agent.name);
    let room = direct_room(&agent.name);
    let mut sock = client
        .open_rooms_socket(Some(&room))
        .await
        .expect("open the room socket");
    // A user post that echoes proves the session is subscribed, so the agent post below cannot be
    // fanned into a socket that is not listening yet.
    drive_until_echo(&client, &mut sock, &room, "before-the-agent").await;

    let text = "the agent's answer";
    let (status, answer) = post_message(
        &client,
        &room,
        ProxyAuth::AgentToken(&token),
        &serde_json::json!({ "text": text }),
    );
    assert_eq!(status, 200, "the agent post lands: {answer}");

    let frame = sock
        .expect_frame_matching(
            |frame| frame["sender"].as_str() == Some(agent.name.as_str()),
            FRAME_TIMEOUT,
        )
        .await
        .expect("the agent's message on the user's room socket");
    assert_eq!(
        frame["type"].as_str(),
        Some("chat"),
        "an agent post is a chat message"
    );
    assert_eq!(frame["text"].as_str(), Some(text));
    assert_eq!(frame["room"].as_str(), Some(room.as_str()));

    let deadline = Instant::now() + NOTIFICATION_TIMEOUT;
    let entry = loop {
        if let Some(entry) = feed_entry_for(&client, &agent.name, text) {
            break entry;
        }
        assert!(
            Instant::now() < deadline,
            "no user notification for {} within {NOTIFICATION_TIMEOUT:?}",
            agent.name
        );
        tokio::time::sleep(POLL_INTERVAL).await;
    };
    assert_eq!(
        entry["kind"].as_str(),
        Some("message"),
        "an agent message notifies as message"
    );
    assert_eq!(
        entry["title"].as_str(),
        Some(agent.name.as_str()),
        "the sender titles the entry"
    );
    assert!(
        entry["id"].as_u64().is_some(),
        "the feed entry carries its log id"
    );
    assert!(
        entry["at"].as_u64().is_some(),
        "the feed entry carries its stamp"
    );
    sock.close().await.ok();
}

/// (5) The burst guard stops an agent that fills a room while the user is silent, and the user's
/// next message clears it.
#[test]
fn the_burst_guard_refuses_the_forty_first_agent_message() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-burst");
    let token = agent_token(&agent.name);
    let room = direct_room(&agent.name);

    for index in 0..BURST_CAP {
        let (status, answer) = post_message(
            &client,
            &room,
            ProxyAuth::AgentToken(&token),
            &serde_json::json!({ "text": format!("burst {index}") }),
        );
        assert_eq!(status, 200, "agent message {index} lands: {answer}");
    }

    let (status, refusal) = post_message(
        &client,
        &room,
        ProxyAuth::AgentToken(&token),
        &serde_json::json!({ "text": "one too many" }),
    );
    assert_eq!(
        status, 429,
        "the message past the cap is refused: {refusal}"
    );
    assert_eq!(refusal["error"].as_str(), Some(BURST_REFUSAL));

    let (status, answer) = post_message(
        &client,
        &room,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "text": "I am back" }),
    );
    assert_eq!(status, 200, "the user's own message lands: {answer}");
    let (status, answer) = post_message(
        &client,
        &room,
        ProxyAuth::AgentToken(&token),
        &serde_json::json!({ "text": "answering you" }),
    );
    assert_eq!(status, 200, "the user's message clears the guard: {answer}");
}

/// (6) While a client reports the user talking, an agent post is refused with the instruction it
/// must read; clearing the floor after such a refusal announces the turn's end to the agent's own
/// unscoped session.
#[tokio::test]
async fn speaking_gates_agent_posts_and_the_floor_clearing_emits_turn_end() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-speaking");
    let token = agent_token(&agent.name);
    let room = direct_room(&agent.name);

    let mut user_sock = client
        .open_rooms_socket(Some(&room))
        .await
        .expect("open the user's room socket");
    // An agent's own session carries its token in a header: it has no query carrier at all.
    let mut agent_sock = client
        .connect_ws_as("/rooms/ws", ProxyAuth::AgentToken(&token))
        .await
        .expect("open the agent's unscoped room socket");
    // Both sessions must be subscribed before the turn-end event fans, or the socket is replay-free
    // against them. An echo on each is that proof.
    drive_until_echo(&client, &mut user_sock, &room, "user-ready").await;
    drive_until_echo(&client, &mut agent_sock, &room, "agent-ready").await;

    user_sock
        .send_client_frame(&serde_json::json!({ "type": "speaking", "active": true }))
        .await
        .expect("report the user talking");

    // The report travels on the socket while the post travels over HTTP, so the gate binds a
    // moment after the frame is sent: retry until it refuses.
    let mut refused = None;
    for _ in 0..GATE_ATTEMPTS {
        let (status, answer) = post_message(
            &client,
            &room,
            ProxyAuth::AgentToken(&token),
            &serde_json::json!({ "text": "interrupting" }),
        );
        if status == 409 {
            refused = Some(answer);
            break;
        }
        assert_eq!(status, 200, "an ungated agent post lands: {answer}");
        tokio::time::sleep(POLL_INTERVAL).await;
    }
    let refusal = refused.expect("the speaking gate refused an agent post");
    assert_eq!(refusal["error"].as_str(), Some(SPEAKING_REFUSAL));
    assert_eq!(
        refusal["user_speaking"].as_bool(),
        Some(true),
        "the refusal names the reason: {refusal}"
    );

    user_sock
        .send_client_frame(&serde_json::json!({ "type": "speaking", "active": false }))
        .await
        .expect("report the user done");
    let turn_end = agent_sock
        .expect_frame_matching(
            |frame| frame["type"].as_str() == Some("user_finished_talking"),
            FRAME_TIMEOUT,
        )
        .await
        .expect("the turn-end event on the agent's session");
    assert_eq!(turn_end["room"].as_str(), Some(room.as_str()));

    user_sock.close().await.ok();
    agent_sock.close().await.ok();
}

/// (7) An agent replays its own history into its direct room: every origin id lands once, a
/// re-import skips them all, and the page reads back in the original stamps' order.
#[test]
fn an_agent_imports_its_history_idempotently() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-import");
    let token = agent_token(&agent.name);
    let room = direct_room(&agent.name);
    // The newer message first, so the ordering assertion below reads the stamps and not the order
    // they were sent in.
    let body = serde_json::json!({
        "messages": [
            {
                "origin_id": 8,
                "ts": "2026-09-04T10:12:04+00:00",
                "type": "chat",
                "text": "the reply"
            },
            {
                "origin_id": 7,
                "ts": "2026-09-04T10:12:03.123456+00:00",
                "type": "user",
                "text": "the question"
            }
        ]
    });

    let (status, raw) = client
        .proxy_post_json(
            &format!("/rooms/{room}/messages/import"),
            ProxyAuth::AgentToken(&token),
            &body,
        )
        .expect("import history");
    assert_eq!(status, 200, "the import lands: {raw}");
    let outcome = parse(&raw);
    assert_eq!(
        outcome["imported"].as_u64(),
        Some(2),
        "both messages import: {outcome}"
    );
    assert_eq!(outcome["skipped"].as_u64(), Some(0));

    let (status, raw) = client
        .proxy_post_json(
            &format!("/rooms/{room}/messages/import"),
            ProxyAuth::AgentToken(&token),
            &body,
        )
        .expect("re-import history");
    assert_eq!(status, 200, "the re-import answers 200: {raw}");
    let outcome = parse(&raw);
    assert_eq!(
        outcome["imported"].as_u64(),
        Some(0),
        "nothing imports twice: {outcome}"
    );
    assert_eq!(outcome["skipped"].as_u64(), Some(2));

    let page = history(&client, &room, "limit=50");
    let events = history_events(&page);
    assert_eq!(
        events.len(),
        2,
        "the room holds the two imported messages: {page}"
    );
    assert_eq!(
        events[0]["origin_id"].as_u64(),
        Some(7),
        "the older stamp reads first: {page}"
    );
    assert_eq!(events[0]["ts"].as_str(), Some("2026-09-04T10:12:03.123Z"));
    assert_eq!(events[0]["sender"].as_str(), Some("user"));
    assert_eq!(events[1]["origin_id"].as_u64(), Some(8));
    assert_eq!(events[1]["ts"].as_str(), Some("2026-09-04T10:12:04Z"));
    assert_eq!(events[1]["sender"].as_str(), Some(agent.name.as_str()));
}

/// (8) A rename carries the direct room to the new name, and a direct room outlives everything but
/// its agent: deletable once the agent is gone, refused while it lives.
#[test]
fn rename_and_delete_follow_the_agent() {
    let client = SERVER.client();
    let mut moving = chat_agent(&client, "rooms-rename");
    let bystander = chat_agent(&client, "rooms-bystander");
    let old_name = moving.name.clone();
    let new_name = unique_agent("rooms-renamed");

    let returned = client
        .rename_agent(&old_name, &new_name)
        .expect("rename the agent");
    assert_eq!(returned, new_name);
    moving.name = new_name.clone(); // let Drop clean the renamed container up

    let ids = room_ids(&list_rooms(&client, ProxyAuth::ApiKey));
    assert!(
        ids.contains(&direct_room(&new_name)),
        "the direct room moved to {}: {ids:?}",
        direct_room(&new_name)
    );
    assert!(
        !ids.contains(&direct_room(&old_name)),
        "the old direct room id is gone: {ids:?}"
    );

    // A direct room lives as long as its agent: the delete is refused while the agent is there.
    let (status, raw) = client
        .proxy_delete(&direct_room_path(&bystander.name), ProxyAuth::ApiKey)
        .expect("delete a live agent's direct room");
    assert_eq!(
        status, 409,
        "a live agent's direct room is not deletable: {raw}"
    );
    assert_eq!(
        parse(&raw)["error"].as_str(),
        Some("a direct room lives as long as its agent")
    );

    client.destroy_agent(&new_name).expect("destroy the agent");
    let (status, raw) = client
        .proxy_delete(&direct_room_path(&new_name), ProxyAuth::ApiKey)
        .expect("delete the destroyed agent's direct room");
    assert_eq!(status, 200, "the room goes once its agent is gone: {raw}");
    assert_eq!(parse(&raw)["ok"].as_bool(), Some(true));

    let ids = room_ids(&list_rooms(&client, ProxyAuth::ApiKey));
    assert!(
        !ids.contains(&direct_room(&new_name)),
        "the deleted room is out of the list: {ids:?}"
    );
}

/// (9) Membership is decided on every room route: an agent that is not in a room reads nothing
/// from it and writes nothing into it, and a request carrying no credential at all never gets a
/// principal to be judged by.
#[test]
fn a_stranger_agent_is_refused_and_no_credential_is_401() {
    let client = SERVER.client();
    let owner = chat_agent(&client, "rooms-owner");
    let stranger = chat_agent(&client, "rooms-stranger");
    let token = agent_token(&stranger.name);
    let room = direct_room(&owner.name);

    let (status, raw) = client
        .proxy_get(
            &format!("/rooms/{room}/history"),
            ProxyAuth::AgentToken(&token),
        )
        .expect("read another agent's history");
    assert_eq!(status, 403, "a stranger reads no history: {raw}");
    assert_eq!(
        parse(&raw)["error"].as_str(),
        Some("not a member of this room")
    );

    let (status, body) = post_message(
        &client,
        &room,
        ProxyAuth::AgentToken(&token),
        &serde_json::json!({ "text": "let me in" }),
    );
    assert_eq!(status, 403, "a stranger posts nothing: {body}");
    assert_eq!(
        body["error"].as_str(),
        Some("not a member of this room"),
        "the refusal names membership, never the room's existence"
    );

    let (status, raw) = client
        .proxy_get("/rooms", ProxyAuth::None)
        .expect("list rooms with no credential");
    assert_eq!(status, 401, "the room list needs a credential: {raw}");
}

/// (10) An upload lands in chunks over its own session, refuses a chunk at the wrong offset with
/// the size to resync to, and the finalized attachment rides a message onto the socket and into
/// history by id alone.
#[tokio::test]
async fn an_upload_lands_in_chunks_and_rides_a_message() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-upload");
    let room = direct_room(&agent.name);
    let mut sock = client
        .open_rooms_socket(Some(&room))
        .await
        .expect("open the room socket");
    drive_until_echo(&client, &mut sock, &room, "before-the-upload").await;

    let (status, raw) = client
        .proxy_post_json(
            ATTACHMENTS_PATH,
            ProxyAuth::ApiKey,
            &serde_json::json!({ "name": "note.txt", "mime": "text/plain", "size": 3 }),
        )
        .expect("create the upload session");
    assert_eq!(status, 200, "POST {ATTACHMENTS_PATH}: {raw}");
    let id = parse(&raw)["id"]
        .as_str()
        .expect("the create answers an id")
        .to_string();

    let (status, raw) = put_chunk(&client, &id, 0, b"ab");
    assert_eq!(status, 200, "the first chunk lands: {raw}");
    assert_eq!(parse(&raw)["received"].as_u64(), Some(2));

    // The same chunk again: the offset the client believes in is behind the staged size, so the
    // refusal carries the truth rather than duplicating the bytes.
    let (status, raw) = put_chunk(&client, &id, 0, b"ab");
    assert_eq!(status, 409, "a replayed offset is refused: {raw}");
    let refusal = parse(&raw);
    assert_eq!(refusal["error"].as_str(), Some("offset mismatch"));
    assert_eq!(
        refusal["received"].as_u64(),
        Some(2),
        "the refusal names the offset to resume from: {raw}"
    );

    let staged = attachment_status(&client, &id);
    assert_eq!(staged["received"].as_u64(), Some(2));
    assert_eq!(staged["size"].as_u64(), Some(3));
    assert_eq!(staged["finalized"].as_bool(), Some(false));

    let (status, raw) = put_chunk(&client, &id, 2, b"c");
    assert_eq!(status, 200, "the last chunk lands: {raw}");
    assert_eq!(parse(&raw)["received"].as_u64(), Some(3));

    let (status, raw) = client
        .proxy_post_json(
            &format!("{ATTACHMENTS_PATH}/{id}/complete"),
            ProxyAuth::ApiKey,
            &serde_json::json!({}),
        )
        .expect("complete the upload");
    assert_eq!(status, 200, "the upload finalizes: {raw}");
    let meta = parse(&raw)["attachment"].clone();
    assert_eq!(meta["id"].as_str(), Some(id.as_str()));
    assert_eq!(meta["name"].as_str(), Some("note.txt"));
    assert_eq!(meta["mime"].as_str(), Some("text/plain"));
    assert_eq!(meta["size"].as_u64(), Some(3));
    assert_eq!(
        attachment_status(&client, &id)["finalized"].as_bool(),
        Some(true),
        "a finalized id reports itself as done"
    );

    let intent = "i-upload-carries";
    let (status, answer) = post_message(
        &client,
        &room,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "text": "here it is", "intent_id": intent, "attachments": [&id] }),
    );
    assert_eq!(status, 200, "the post carrying the id lands: {answer}");

    let echo = sock
        .expect_frame_matching(
            |frame| frame["intent_id"].as_str() == Some(intent),
            FRAME_TIMEOUT,
        )
        .await
        .expect("the attachment message on the room socket");
    assert_eq!(
        echo["attachments"],
        serde_json::json!([meta]),
        "the echo carries the whole metadata, not merely the id"
    );

    let carried = history_events(&history(&client, &room, "limit=50"))
        .into_iter()
        .find(|event| event["intent_id"].as_str() == Some(intent))
        .expect("the attachment message pages back");
    assert_eq!(carried["attachments"], serde_json::json!([meta]));
}

/// (11) What a browser is told about a blob: media renders inline, a download is asked for on
/// request, and anything else is an opaque stream it can only save.
#[test]
fn a_blob_serves_inline_for_media_and_downloads_otherwise() {
    let client = SERVER.client();
    let image = upload_attachment(&client, "photo.png", "image/png", PNG_MAGIC);
    let page = upload_attachment(&client, "page.html", "text/html", b"<b>hi</b>");

    let (status, headers) = client
        .proxy_get_headers(&format!("{ATTACHMENTS_PATH}/{image}"), ProxyAuth::ApiKey)
        .expect("serve the image");
    assert_eq!(status, 200, "the image serves");
    assert_eq!(
        header(&headers, "content-type").as_deref(),
        Some("image/png")
    );
    assert!(
        header(&headers, "content-disposition")
            .is_some_and(|value| value.starts_with("inline; filename=\"photo.png\"")),
        "media renders inline: {:?}",
        header(&headers, "content-disposition")
    );
    assert_eq!(
        header(&headers, "x-content-type-options").as_deref(),
        Some("nosniff")
    );

    let (status, headers) = client
        .proxy_get_headers(
            &format!("{ATTACHMENTS_PATH}/{image}?download=1"),
            ProxyAuth::ApiKey,
        )
        .expect("serve the image as a download");
    assert_eq!(status, 200, "the download serves");
    assert_eq!(
        header(&headers, "content-type").as_deref(),
        Some("image/png"),
        "a download keeps the real type it declared"
    );
    assert!(
        header(&headers, "content-disposition")
            .is_some_and(|value| value.starts_with("attachment; filename=\"photo.png\"")),
        "a download is saved, never rendered: {:?}",
        header(&headers, "content-disposition")
    );

    let (status, headers) = client
        .proxy_get_headers(&format!("{ATTACHMENTS_PATH}/{page}"), ProxyAuth::ApiKey)
        .expect("serve the html blob");
    assert_eq!(status, 200, "the html blob serves");
    assert_eq!(
        header(&headers, "content-type").as_deref(),
        Some("application/octet-stream"),
        "a declared mime that is not media is served opaquely"
    );
    assert!(
        header(&headers, "content-disposition")
            .is_some_and(|value| value.starts_with("attachment; filename=\"page.html\"")),
        "a non-media blob is never rendered: {:?}",
        header(&headers, "content-disposition")
    );
}

/// (12) A post naming an attachment this node never finalized is refused by id, and the message
/// it carried lands nowhere.
#[test]
fn an_unknown_attachment_id_is_a_400_on_post() {
    let client = SERVER.client();
    let agent = chat_agent(&client, "rooms-unknown-attachment");
    let room = direct_room(&agent.name);

    let (status, body) = post_message(
        &client,
        &room,
        ProxyAuth::ApiKey,
        &serde_json::json!({ "text": "with a ghost", "attachments": [UNKNOWN_ATTACHMENT_ID] }),
    );
    assert_eq!(status, 400, "an unknown id is refused: {body}");
    assert_eq!(
        body["error"].as_str(),
        Some(format!("unknown attachment: {UNKNOWN_ATTACHMENT_ID}").as_str()),
        "the refusal names the id it could not resolve"
    );

    let landed = history_events(&history(&client, &room, "limit=50"))
        .into_iter()
        .any(|event| event["text"].as_str() == Some("with a ghost"));
    assert!(!landed, "a refused post persists nothing");
}
