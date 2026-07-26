//! End-to-end proof of the service-key gate against the real vestad proxy and a real agent
//! container: a private service is reachable only with the api key or a live service key, the
//! key works in the path prefix an iframe's sub-resources inherit, revoking it takes effect
//! immediately, and vestad hands its inner-proxy agent token to the raw agent port alone.

use vesta_tests::{
    agent_container_name, exec_in_container, unique_agent, ProxyAuth, TestAgent, SERVER,
};

const AGENT_RUNNING_TIMEOUT_SECS: u64 = 60;

/// A throwaway upstream that answers every GET with the request headers it received, as a JSON
/// object keyed by lowercased header name. Lets a test assert on exactly what the proxy forwarded.
const HEADER_ECHO_UPSTREAM: &str = r#"cat > /tmp/header-echo.py <<'PY'
import http.server
import json
import sys


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({k.lower(): v for k, v in self.headers.items()}).encode()
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
    let forwarded: serde_json::Map<String, serde_json::Value> =
        serde_json::from_str(&body).expect("the upstream echoes its request headers as JSON");
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
