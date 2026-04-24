use vesta_tests::{TestAgent, SERVER, unique_agent};

fn read_agent_token(agent_name: &str) -> String {
    let env_path = SERVER
        ._tmpdir_path()
        .join(format!(".config/vesta/vestad/agents/{}.env", agent_name));
    let content = std::fs::read_to_string(&env_path).expect("per-agent env file should exist");
    let line = content
        .lines()
        .find(|l| l.contains("AGENT_TOKEN="))
        .expect("env file should contain AGENT_TOKEN");
    line.strip_prefix("export AGENT_TOKEN=")
        .expect("should have export prefix")
        .to_string()
}

fn register_dashboard(agent: &str, token: &str) {
    let c = SERVER.client();
    c.register_service(
        agent,
        token,
        &serde_json::json!({"name": "dashboard"}),
    )
    .expect("register dashboard service");
}

#[test]
fn create_session_requires_api_key() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-auth")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    let resp = c
        .raw_agent()
        .post(&format!(
            "{}/agents/{}/services/dashboard/session",
            c.base_url(),
            agent.name,
        ))
        .send_empty()
        .unwrap();
    assert_eq!(resp.status().as_u16(), 401, "missing bearer should be 401");
}

#[test]
fn create_session_returns_404_for_unregistered_service() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-404")).unwrap();

    let (status, body) = c
        .post_raw(&format!("/agents/{}/services/dashboard/session", agent.name))
        .unwrap();
    assert_eq!(status, 404, "unregistered service should be 404, got body: {body}");
}

#[test]
fn create_session_happy_path_returns_url_and_expiry() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-ok")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    let resp = c.create_service_session(&agent.name, "dashboard").unwrap();
    let session_id = resp["session_id"].as_str().expect("session_id");
    let url = resp["url"].as_str().expect("url");
    let expires_in = resp["expires_in"].as_u64().expect("expires_in");

    assert_eq!(session_id.len(), 64, "256-bit hex session id");
    assert!(session_id.chars().all(|c| c.is_ascii_hexdigit()), "hex only");
    assert_eq!(
        url,
        format!("/agents/{}/services/dashboard/s/{}/", agent.name, session_id),
    );
    assert!(expires_in > 0 && expires_in <= 3600, "sane TTL: {}", expires_in);
}

#[test]
fn proxy_rejects_unknown_session_id() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-bad")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    let (status, body) = c
        .get_raw_no_auth(&format!(
            "/agents/{}/services/dashboard/s/{}/",
            agent.name,
            "0".repeat(64),
        ))
        .unwrap();
    assert_eq!(status, 401, "bogus session must 401, got body: {body}");
}

#[test]
fn proxy_rejects_session_for_wrong_service_name() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-xsvc")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    // Register a second service so we have a valid target to misdirect to.
    c.register_service(
        &agent.name,
        &token,
        &serde_json::json!({"name": "other"}),
    )
    .unwrap();

    let resp = c.create_service_session(&agent.name, "dashboard").unwrap();
    let sid = resp["session_id"].as_str().unwrap();

    let (status, body) = c
        .get_raw_no_auth(&format!(
            "/agents/{}/services/other/s/{}/",
            agent.name, sid,
        ))
        .unwrap();
    assert_eq!(status, 404, "session from other service must not cross, got body: {body}");
}

#[test]
fn proxy_accepts_valid_session_without_bearer() {
    // We don't need a real upstream — vestad will return 502 when the
    // registered service port has nothing listening, but 502 is proof the
    // session auth passed. A 401 would indicate the session check didn't.
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-fwd")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    let resp = c.create_service_session(&agent.name, "dashboard").unwrap();
    let sid = resp["session_id"].as_str().unwrap();

    let (status, _body) = c
        .get_raw_no_auth(&format!(
            "/agents/{}/services/dashboard/s/{}/",
            agent.name, sid,
        ))
        .unwrap();
    assert_ne!(status, 401, "valid session should not 401");
    assert_ne!(status, 404, "valid session should not 404");
    // Likely 502 (no upstream) or 504 (timeout). Anything that isn't an auth
    // rejection is proof the session check passed.
    assert!(
        (500..=599).contains(&status) || status == 200,
        "expected upstream-error or 200, got {}",
        status,
    );
}

#[test]
fn invalidate_service_busts_sessions() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("svc-sess-inv")).unwrap();
    let token = read_agent_token(&agent.name);
    register_dashboard(&agent.name, &token);

    let resp = c.create_service_session(&agent.name, "dashboard").unwrap();
    let sid = resp["session_id"].as_str().unwrap().to_string();

    // Fire the invalidate endpoint with X-Agent-Token (matches how the agent
    // calls it after a rebuild).
    let resp = c
        .raw_agent()
        .post(&format!(
            "{}/agents/{}/services/dashboard/invalidate",
            c.base_url(),
            agent.name,
        ))
        .header("X-Agent-Token", &token)
        .send_empty()
        .unwrap();
    assert_eq!(resp.status().as_u16(), 200, "invalidate should succeed");

    let (status, body) = c
        .get_raw_no_auth(&format!(
            "/agents/{}/services/dashboard/s/{}/",
            agent.name, sid,
        ))
        .unwrap();
    assert_eq!(status, 401, "invalidate must have dropped the session, got body: {body}");
}
