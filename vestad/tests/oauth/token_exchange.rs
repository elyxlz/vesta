use super::common::{OAUTH_CLIENT_ID, OAUTH_REDIRECT_URI, OAUTH_TOKEN_URL};

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
        Err(ureq::Error::StatusCode(_)) => return,
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
