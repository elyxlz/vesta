/// Verify Anthropic's OAuth endpoints are reachable.
/// Catches endpoint migrations (e.g. console.anthropic.com → platform.claude.com).

fn check_endpoint(url: &str) {
    let agent = ureq::Agent::new_with_defaults();
    let result = agent.get(url).call();
    match result {
        Ok(resp) => assert!(
            resp.status().as_u16() < 500,
            "{url} returned {}",
            resp.status()
        ),
        Err(ureq::Error::StatusCode(code)) => assert!(
            code < 500,
            "{url} returned {code}"
        ),
        Err(e) => panic!("{url} unreachable: {e}"),
    }
}

#[test]
fn oauth_authorize_endpoint_reachable() {
    check_endpoint("https://platform.claude.com/oauth/authorize");
}

#[test]
fn oauth_token_endpoint_reachable() {
    check_endpoint("https://platform.claude.com/v1/oauth/token");
}

#[test]
fn oauth_callback_endpoint_reachable() {
    check_endpoint("https://platform.claude.com/oauth/code/callback");
}
