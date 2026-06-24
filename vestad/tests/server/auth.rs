use vesta_tests::{TestAgent, SERVER, mark_first_start_done, unique_agent};

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
fn agent_without_credentials_is_not_authenticated() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("no-creds")).unwrap();

    // No credentials are injected, so the agent re-derives provider state on restart
    // and settles at not_authenticated. A fake token can't reach `authenticated` (the
    // agent's first turn 401s upstream and flips it back), so the authenticated path
    // is covered by the live tests with real credentials, not here.
    mark_first_start_done(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    let status = c.wait_until_running(&agent.name, 180).unwrap();
    assert_eq!(status, "not_authenticated");
}
