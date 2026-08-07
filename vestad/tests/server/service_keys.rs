//! End-to-end proof of the service-key gate against the real vestad proxy and a real agent
//! container: a private service is reachable only with the api key or a live service key, the
//! key works in the path prefix an iframe's sub-resources inherit and in the query string a
//! WebSocket upgrade is limited to, revoking it takes effect immediately on both, the mint and
//! revoke endpoints are authenticated and self-scoped to one agent, vestad hands its
//! inner-proxy agent token to the raw agent port alone, and the client credential the proxy
//! consumed (Authorization header, `?token=` pair) never reaches an upstream.

use vesta_tests::{
    agent_container_name, exec_in_container, unique_agent, ProxyAuth, TestAgent, SERVER,
};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 60;

/// A throwaway upstream that answers every GET with the request it received, as JSON:
/// `path` (the request line's path and query, verbatim) and `headers` (keyed by lowercased
/// name). Lets a test assert on exactly what the proxy forwarded.
const HEADER_ECHO_UPSTREAM: &str = r#"cat > /tmp/header-echo.py <<'PY'
import http.server
import json
import sys


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


http.server.HTTPServer(("0.0.0.0", int(sys.argv[1])), Handler).serve_forever()
PY
screen -dmS header-echo python3 /tmp/header-echo.py"#;

/// Create a running agent with `service` registered, backed by the header-echo upstream.
/// Returns the agent handle (kept alive by the caller so its Drop still destroys it).
fn agent_serving<'client>(
    client: &'client vesta_tests::client::Client,
    prefix: &str,
    service: &str,
) -> (TestAgent<'client>, serde_json::Value) {
    let agent = TestAgent::create(client, &unique_agent(prefix)).expect("create agent");
    client.start_agent(&agent.name).expect("start agent");
    client
        .wait_until_running(&agent.name, AGENT_RUNNING_TIMEOUT_SECS)
        .expect("agent running");

    let registered = client
        .register_service(&agent.name, service)
        .expect("register service");
    let port = registered["port"].as_u64().expect("port in response");
    exec_in_container(
        &agent_container_name(&agent.name),
        &format!("{HEADER_ECHO_UPSTREAM} {port}"),
    )
    .expect("start header-echo upstream");
    (agent, registered)
}

#[test]
fn a_private_service_needs_the_api_key_or_a_live_service_key() {
    let client = SERVER.client();
    let (agent, registered) = agent_serving(&client, "svc-key", "dashboard");
    assert_eq!(
        registered["public"].as_bool(),
        Some(false),
        "a registration that does not ask for exposure is private"
    );

    let minted = client
        .mint_service_key(&agent.name, "dashboard")
        .expect("mint service key");
    let key = minted["key"]
        .as_str()
        .expect("secret in mint response")
        .to_string();
    let id = minted["id"]
        .as_str()
        .expect("id in mint response")
        .to_string();
    assert_eq!(key.len(), 64, "the secret is 32 bytes of hex");

    let keyed = format!("/agents/{}/dashboard/k/{}/", agent.name, key);
    let wrong = format!(
        "/agents/{}/dashboard/k/{}/",
        agent.name,
        "deadbeef".repeat(8)
    );
    let bare = format!("/agents/{}/dashboard/", agent.name);

    assert_eq!(
        client.proxy_status(&keyed, ProxyAuth::None).unwrap(),
        200,
        "a live key in the path authenticates and forwards"
    );
    assert_eq!(
        client.proxy_status(&wrong, ProxyAuth::None).unwrap(),
        401,
        "a wrong key does not authenticate"
    );
    assert_eq!(
        client.proxy_status(&bare, ProxyAuth::None).unwrap(),
        401,
        "a private service with no credential is refused"
    );
    assert_eq!(
        client.proxy_status(&bare, ProxyAuth::ApiKey).unwrap(),
        200,
        "the api key still opens a private service"
    );
    assert_eq!(
        client.proxy_status(&bare, ProxyAuth::Bearer(&key)).unwrap(),
        200,
        "the same key works as a Bearer header"
    );
    assert_eq!(
        client
            .proxy_status(&format!("{bare}?token={key}"), ProxyAuth::None)
            .unwrap(),
        200,
        "and as a query param"
    );

    client
        .revoke_service_key(&agent.name, "dashboard", &id)
        .expect("revoke service key");
    assert_eq!(
        client.proxy_status(&keyed, ProxyAuth::None).unwrap(),
        401,
        "revocation takes effect immediately"
    );
}

/// A WebSocket upgrade is gated by the very same decision as a plain GET: `proxy_authorized` runs
/// and can 401 before the handler looks at `Upgrade` at all, so a live key in `?token=` completes
/// the handshake and a revoked one is refused with a 401 in place of the 101. That is what lets a
/// browser socket (the app-chat live chat socket) authenticate with a key it can only put in the
/// query string. The upstream here speaks plain HTTP, so the socket closes right after the
/// handshake: the handshake IS the gate's verdict, and the data path behind it is driven for real
/// against the app-chat daemon in `sync.rs`.
#[tokio::test]
async fn a_service_key_opens_a_websocket_upgrade_until_it_is_revoked() {
    let client = SERVER.client();
    let (agent, _) = agent_serving(&client, "svc-key-ws", "dashboard");

    let minted = client
        .mint_service_key(&agent.name, "dashboard")
        .expect("mint service key");
    let key = minted["key"]
        .as_str()
        .expect("secret in mint response")
        .to_string();
    let id = minted["id"]
        .as_str()
        .expect("id in mint response")
        .to_string();

    let keyed_ws = format!("/agents/{}/dashboard/live?token={}", agent.name, key);
    let bare_ws = format!("/agents/{}/dashboard/live", agent.name);

    client
        .connect_ws(&keyed_ws)
        .await
        .expect("a live key completes the ws handshake");

    assert_ws_upgrade_refused(&client, &bare_ws, "no credential at all").await;

    client
        .revoke_service_key(&agent.name, "dashboard", &id)
        .expect("revoke service key");
    assert_ws_upgrade_refused(&client, &keyed_ws, "a revoked key").await;
}

/// Assert a ws upgrade is refused with a 401 before anything upgrades: tungstenite reports a
/// non-101 response as `HTTP error: {status}`. A match rather than `expect_err` because the success
/// type is a live socket, which is not `Debug`.
async fn assert_ws_upgrade_refused(
    client: &vesta_tests::client::Client,
    path_and_query: &str,
    context: &str,
) {
    match client.connect_ws(path_and_query).await {
        Ok(_) => panic!("{context}: the ws upgrade completed instead of being refused"),
        Err(error) => assert!(
            error.contains("401"),
            "{context}: expected a 401 ws upgrade, got: {error}"
        ),
    }
}

/// Minting is a real privilege, so the endpoints behind it are authenticated and self-scoped:
/// an agent's own token mints and revokes for its own services and for nobody else's. The
/// mutation this pins is one word in `serve.rs`, `auth_middleware_api_or_any_agent_token` in
/// place of `auth_middleware_api_or_agent_token`, which would let every agent on the host mint
/// a permanent key for every other agent's services.
#[test]
fn key_endpoints_are_authenticated_and_scoped_to_one_agent() {
    let client = SERVER.client();
    let (owner, _) = agent_serving(&client, "svc-scope-a", "dashboard");
    let (other, _) = agent_serving(&client, "svc-scope-b", "dashboard");
    let owner_token = client
        .read_agent_token(&owner.name)
        .expect("owner agent token");

    let (unauthenticated, body) = client
        .mint_service_key_as(&owner.name, "dashboard", ProxyAuth::None)
        .expect("mint request reaches vestad");
    assert_eq!(
        unauthenticated, 401,
        "minting with no credential is refused, got: {body}"
    );

    let (own_status, own_body) = client
        .mint_service_key_as(&owner.name, "dashboard", ProxyAuth::AgentToken(&owner_token))
        .expect("mint request reaches vestad");
    assert_eq!(
        own_status, 200,
        "an agent's own token mints for its own service, got: {own_body}"
    );
    let own_key: serde_json::Value =
        serde_json::from_str(&own_body).expect("mint response is JSON");
    let key = own_key["key"].as_str().expect("secret in mint response");
    assert_eq!(
        client
            .proxy_status(
                &format!("/agents/{}/dashboard/", owner.name),
                ProxyAuth::Bearer(key)
            )
            .unwrap(),
        200,
        "the self-minted key opens the service it is scoped to"
    );

    let (cross_mint, cross_body) = client
        .mint_service_key_as(&other.name, "dashboard", ProxyAuth::AgentToken(&owner_token))
        .expect("mint request reaches vestad");
    assert_eq!(
        cross_mint, 401,
        "one agent's token must not mint for another agent's service, got: {cross_body}"
    );

    let victim = client
        .mint_service_key(&other.name, "dashboard")
        .expect("mint a key belonging to the other agent");
    let victim_id = victim["id"].as_str().expect("id in mint response");
    let victim_key = victim["key"].as_str().expect("secret in mint response");
    assert_eq!(
        client
            .revoke_service_key_as(
                &other.name,
                "dashboard",
                victim_id,
                ProxyAuth::AgentToken(&owner_token)
            )
            .expect("revoke request reaches vestad"),
        401,
        "one agent's token must not revoke another agent's key"
    );
    assert_eq!(
        client
            .proxy_status(
                &format!("/agents/{}/dashboard/", other.name),
                ProxyAuth::Bearer(victim_key)
            )
            .unwrap(),
        200,
        "and the refused revoke left that key live"
    );
}

/// The `headers` object out of an echo-upstream response body.
fn echoed_headers(body: &str) -> serde_json::Map<String, serde_json::Value> {
    let echoed: serde_json::Value =
        serde_json::from_str(body).expect("the upstream echoes its request as JSON");
    echoed["headers"]
        .as_object()
        .expect("echoed headers object")
        .clone()
}

/// The `path` (path and query, verbatim) out of an echo-upstream response body.
fn echoed_path(body: &str) -> String {
    let echoed: serde_json::Value =
        serde_json::from_str(body).expect("the upstream echoes its request as JSON");
    echoed["path"]
        .as_str()
        .expect("echoed request path")
        .to_string()
}

/// The credential that authorizes a proxied request is consumed by vestad, whichever carrier
/// it rode in: the Authorization header never reaches the upstream, and the `?token=` pair is
/// dropped from the forwarded query while every other pair survives. A registered private
/// service "verifies nothing itself", so nothing downstream may see a gateway-tier secret.
#[test]
fn the_consumed_client_credential_never_reaches_the_upstream() {
    let client = SERVER.client();
    let (agent, _) = agent_serving(&client, "svc-strip", "probe");

    let (status, body) = client
        .proxy_get(
            &format!("/agents/{}/probe/echo?lang=en&fmt=json", agent.name),
            ProxyAuth::ApiKey,
        )
        .expect("reach the registered service with the api key");
    assert_eq!(status, 200, "the api key opens the service, got: {body}");
    assert!(
        !echoed_headers(&body).contains_key("authorization"),
        "the Authorization header the proxy consumed must not be forwarded, got: {body}"
    );
    assert_eq!(
        echoed_path(&body),
        "/echo?lang=en&fmt=json",
        "a credential-free query is forwarded verbatim"
    );

    let minted = client
        .mint_service_key(&agent.name, "probe")
        .expect("mint service key");
    let key = minted["key"].as_str().expect("secret in mint response");
    let (status, body) = client
        .proxy_get(
            &format!("/agents/{}/probe/echo?lang=en&token={key}&fmt=json", agent.name),
            ProxyAuth::None,
        )
        .expect("reach the registered service with a query-string service key");
    assert_eq!(status, 200, "the service key opens the service, got: {body}");
    assert_eq!(
        echoed_path(&body),
        "/echo?lang=en&fmt=json",
        "the token= pair is dropped from the forwarded query and the rest survives"
    );
    assert!(
        !echoed_headers(&body).contains_key("authorization"),
        "no Authorization header materializes upstream, got: {body}"
    );
}

/// The agent token is vestad's inner-proxy credential for the raw agent port, never a
/// credential a registered service receives. The service side is observed directly (the
/// upstream echoes its request headers); the raw-port side is observed through the agent's own
/// API, which answers 401 to a request carrying no `X-Agent-Token`.
#[test]
fn only_the_raw_agent_port_receives_the_injected_agent_token() {
    let client = SERVER.client();
    let (agent, _) = agent_serving(&client, "svc-inject", "probe");

    let (status, body) = client
        .proxy_get(&format!("/agents/{}/probe/", agent.name), ProxyAuth::ApiKey)
        .expect("reach the registered service");
    assert_eq!(status, 200, "the api key opens the registered service");
    let forwarded = echoed_headers(&body);
    assert!(
        forwarded.contains_key("host"),
        "expected the echoed headers, got: {body}"
    );
    assert!(
        !forwarded.contains_key("x-agent-token"),
        "a registered service must never be handed the agent token, got: {body}"
    );

    // No service is registered as `status`, so this falls through to the raw agent port. The
    // agent's own API accepts only X-Agent-Token, so a 200 here is the injection happening.
    let (raw_status, raw_body) = client
        .proxy_get(&format!("/agents/{}/status", agent.name), ProxyAuth::ApiKey)
        .expect("reach the raw agent port");
    assert_eq!(
        raw_status, 200,
        "the raw agent port still receives the injected agent token, got: {raw_body}"
    );
    assert!(
        raw_body.contains("setup_complete"),
        "expected the agent's own status payload, got: {raw_body}"
    );
}
