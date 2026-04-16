use super::common::{check_endpoint, OAUTH_TOKEN_URL};

#[test]
fn oauth_authorize_endpoint_reachable() {
    check_endpoint("https://claude.ai/oauth/authorize");
}

#[test]
fn oauth_token_endpoint_reachable() {
    check_endpoint(OAUTH_TOKEN_URL);
}

#[test]
fn oauth_callback_endpoint_reachable() {
    check_endpoint("https://console.anthropic.com/oauth/code/callback");
}
