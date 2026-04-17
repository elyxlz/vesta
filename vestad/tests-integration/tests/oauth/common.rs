pub const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
pub const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
pub const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";

pub fn check_endpoint(url: &str) {
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
