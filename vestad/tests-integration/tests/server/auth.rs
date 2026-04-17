use vesta_tests::{TestAgent, SERVER, inject_fake_token, unique_agent};

#[test]
fn start_auth_returns_url() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("auth-flow")).unwrap();
    let auth = c.start_auth(&agent.name).unwrap();
    assert!(!auth.auth_url.is_empty());
    assert!(!auth.session_id.is_empty());
    assert!(auth.auth_url.contains("oauth"));
}

#[test]
fn complete_auth_bad_session_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("auth-bad")).unwrap();
    assert!(c.complete_auth(&agent.name, "bogus-session", "bogus-code").is_err());
}

#[test]
fn inject_token_marks_authenticated() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("inject-tok")).unwrap();

    inject_fake_token(&c, &agent.name);
    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "not_authenticated");
}
