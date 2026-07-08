//! End-to-end proof that a non-public service is reachable through the proxy only
//! with its per-service key in the path (`/agents/{name}/{service}/k/{key}/`), and
//! is otherwise a 401. Drives the real vestad proxy against a real agent container
//! running a throwaway upstream.

use vesta_tests::{agent_container_name, exec_in_container, unique_agent, ProxyAuth, TestAgent, SERVER};

fn agent_token(name: &str) -> String {
    let env_path = SERVER
        ._tmpdir_path()
        .join(format!(".config/vesta/vestad/agents/{}.env", name));
    let content = std::fs::read_to_string(&env_path).expect("per-agent env file should exist");
    content
        .lines()
        .find(|l| l.contains("AGENT_TOKEN="))
        .and_then(|l| l.strip_prefix("export AGENT_TOKEN="))
        .expect("env file should contain AGENT_TOKEN")
        .to_string()
}

#[test]
fn non_public_service_requires_path_key() {
    let c = SERVER.client();
    let name = unique_agent("svc-key");
    let agent = TestAgent::create(&c, &name).unwrap();
    c.start_agent(&agent.name).unwrap();

    let token = agent_token(&agent.name);

    // Register a non-public service the way the dashboard skill does (agent token).
    let reg = c
        .register_service_as_agent(&agent.name, "dashboard", &token)
        .expect("register service");
    let port = reg["port"].as_u64().expect("port in register response");
    assert_eq!(reg["public"].as_bool(), Some(false), "service must not be public");

    // Stand up a trivial upstream on the service port inside the container so a
    // successfully-authenticated request gets a real 200 (host networking => the
    // container's 0.0.0.0:{port} is the host loopback vestad proxies to).
    let cname = agent_container_name(&agent.name);
    exec_in_container(
        &cname,
        &format!("screen -dmS upstream python3 -m http.server {port} --bind 0.0.0.0"),
    )
    .expect("start upstream");

    // Read the key vestad minted (delivered to the app in the services payload).
    let services = c.services_json(&agent.name).expect("list services");
    let key = services["services"]["dashboard"]["key"]
        .as_str()
        .expect("service entry carries a key")
        .to_string();
    assert_eq!(key.len(), 64, "key is 32 bytes hex");

    let good = format!("/agents/{}/dashboard/k/{}/", agent.name, key);
    let wrong = format!("/agents/{}/dashboard/k/{}/", agent.name, "deadbeef".repeat(8));
    let no_key = format!("/agents/{}/dashboard/", agent.name);

    // Valid key, no auth header (the plain iframe request) -> forwarded (200).
    let valid = c.proxy_status(&good, ProxyAuth::None).expect("valid-key request");
    // Wrong key, no auth -> not forwarded, 401.
    let wrong_key = c.proxy_status(&wrong, ProxyAuth::None).expect("wrong-key request");
    // No key, no auth, non-public service -> 401.
    let missing = c.proxy_status(&no_key, ProxyAuth::None).expect("no-key request");
    // No key but a valid API token still authenticates (the app/CLI direct path).
    let with_token = c.proxy_status(&no_key, ProxyAuth::ApiKey).expect("api-key request");

    eprintln!("VALID key (no auth)   -> {valid}");
    eprintln!("WRONG key (no auth)   -> {wrong_key}");
    eprintln!("NO key   (no auth)    -> {missing}");
    eprintln!("NO key   (api token)  -> {with_token}");

    assert_eq!(valid, 200, "valid path key should authenticate and forward upstream");
    assert_eq!(wrong_key, 401, "a wrong key must not authenticate");
    assert_eq!(missing, 401, "a non-public service with no key must be a 401");
    assert_eq!(with_token, 200, "a valid API token must still authenticate");
}
