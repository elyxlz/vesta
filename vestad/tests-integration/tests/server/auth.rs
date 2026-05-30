use vesta_tests::{TestAgent, SERVER, inject_fake_token, unique_agent};

#[test]
fn oauth_start_returns_url() {
    let c = SERVER.client();
    let auth = c.oauth_start().unwrap();
    assert!(!auth.auth_url.is_empty());
    assert!(!auth.session_id.is_empty());
    assert!(auth.auth_url.contains("oauth"));
}

#[test]
fn oauth_complete_bad_session_fails() {
    let c = SERVER.client();
    assert!(c.oauth_complete("bogus-session", "bogus-code").is_err());
}

#[test]
fn inject_token_marks_authenticated() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("inject-tok")).unwrap();

    inject_fake_token(&c, &agent.name);
    let st = c.agent_status(&agent.name).unwrap();
    assert_ne!(st.status, "not_authenticated");
}
