/// Verify Anthropic's OAuth endpoints are reachable and accept the expected request format.
/// Catches endpoint migrations and request format changes.

const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";

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

/// POST a dummy token exchange with the exact headers/format we use in production.
/// A working endpoint returns a JSON error about the invalid code (400/401/403).
/// "Invalid request format" or a non-JSON response means the format is wrong or
/// the endpoint moved — fail loudly so we catch it before users do.
#[test]
fn oauth_token_exchange_format_accepted() {
    let agent = ureq::Agent::new_with_defaults();
    let body = serde_json::json!({
        "grant_type": "authorization_code",
        "code": "dummy",
        "state": "dummy",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": "dummy",
    });

    let result = agent
        .post(OAUTH_TOKEN_URL)
        .header("User-Agent", "axios/1.13.6")
        .content_type("application/json")
        .send(body.to_string().as_bytes());

    let status = match &result {
        Ok(resp) => resp.status().as_u16(),
        Err(ureq::Error::StatusCode(code)) => *code,
        Err(e) => panic!("token endpoint unreachable: {e}"),
    };

    assert!(status < 500, "token endpoint returned {status}");

    let response_str = match result {
        Ok(resp) => resp.into_body().read_to_string().unwrap(),
        Err(ureq::Error::StatusCode(_)) => return, // 4xx without body is fine
        Err(_) => unreachable!(),
    };

    let parsed: serde_json::Value = serde_json::from_str(&response_str)
        .unwrap_or_else(|_| panic!("token endpoint returned non-JSON: {response_str}"));

    if let Some(msg) = parsed.pointer("/error/message").and_then(|v| v.as_str()) {
        assert!(
            !msg.contains("Invalid request format"),
            "token endpoint rejected our request format — the expected headers/body may have changed"
        );
    }
}
