use vesta_tests::{TestAgent, SERVER, inject_fake_token, mark_first_start_done, unique_agent};

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

    // Credentials land in the container fs; the agent re-derives provider state
    // on restart and then reports authenticated.
    inject_fake_token(&c, &agent.name);
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    let status = c.wait_until_running(&agent.name, 180).unwrap();
    assert_eq!(status, "alive");
}
