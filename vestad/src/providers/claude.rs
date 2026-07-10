//! Claude OAuth handlers. Standalone PKCE dance: the caller gets credentials
//! back and sends them to `PUT /agents/{name}/provider` (then restarts the agent to apply).

use axum::{Json, extract::State, http::StatusCode};
use ring::rand::SecureRandom;
use serde::{Deserialize, Serialize};

use crate::state::{err_response, AuthSession, SharedState};

const OAUTH_HTTP_TIMEOUT_SECS: u64 = 30;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;

const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

#[derive(Serialize)]
pub struct OAuthStartResponse {
    pub auth_url: String,
    pub session_id: String,
}

#[derive(Deserialize)]
pub struct OAuthCompleteBody {
    pub session_id: String,
    pub code: String,
}

pub async fn oauth_start_handler(
    State(state): State<SharedState>,
) -> Result<Json<OAuthStartResponse>, (StatusCode, Json<serde_json::Value>)> {
    let (auth_url, code_verifier, auth_state) = start_auth_flow();
    let session_id: String = (0..16)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect();

    state.clean_expired_sessions().await;

    let mut sessions = state.auth_sessions.lock().await;
    sessions.insert(
        session_id.clone(),
        AuthSession {
            code_verifier,
            state: auth_state,
            created: std::time::Instant::now(),
        },
    );

    Ok(Json(OAuthStartResponse { auth_url, session_id }))
}

pub async fn oauth_complete_handler(
    State(state): State<SharedState>,
    Json(body): Json<OAuthCompleteBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    state.clean_expired_sessions().await;

    let session = {
        let mut sessions = state.auth_sessions.lock().await;
        sessions
            .remove(&body.session_id)
            .ok_or_else(|| err_response(StatusCode::BAD_REQUEST, "invalid or expired auth session — restart the auth flow with POST /providers/claude/oauth/start"))?
    };

    let credentials = complete_auth_flow(&state.http_client, &body.code, &session.code_verifier, &session.state)
        .await
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;

    Ok(Json(serde_json::json!({ "credentials": credentials })))
}

fn percent_encode(s: &str) -> String {
    let mut out = String::with_capacity(s.len() * 3);
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(b as char);
            }
            _ => {
                out.push('%');
                out.push(char::from(b"0123456789ABCDEF"[(b >> 4) as usize]));
                out.push(char::from(b"0123456789ABCDEF"[(b & 0xf) as usize]));
            }
        }
    }
    out
}

fn base64url_encode(data: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(data)
}

fn generate_pkce() -> (String, String) {
    let rng = ring::rand::SystemRandom::new();
    let mut verifier_bytes = [0u8; 32];
    rng.fill(&mut verifier_bytes).expect("random failed");
    let verifier = base64url_encode(&verifier_bytes);

    let challenge_hash = ring::digest::digest(&ring::digest::SHA256, verifier.as_bytes());
    let challenge = base64url_encode(challenge_hash.as_ref());

    (verifier, challenge)
}

fn generate_state() -> String {
    let rng = ring::rand::SystemRandom::new();
    let mut state_bytes = [0u8; 32];
    rng.fill(&mut state_bytes).expect("random failed");
    base64url_encode(&state_bytes)
}

/// Start the OAuth PKCE flow. Returns (auth_url, code_verifier, state).
fn start_auth_flow() -> (String, String, String) {
    let (code_verifier, code_challenge) = generate_pkce();
    let state = generate_state();

    let auth_url = format!(
        "{}?code=true&client_id={}&redirect_uri={}&response_type=code&scope={}&code_challenge={}&code_challenge_method=S256&state={}",
        OAUTH_AUTHORIZE_URL,
        OAUTH_CLIENT_ID,
        percent_encode(OAUTH_REDIRECT_URI),
        percent_encode("org:create_api_key user:profile user:inference"),
        code_challenge,
        state,
    );

    (auth_url, code_verifier, state)
}

/// Complete the OAuth flow by exchanging the auth code for tokens.
/// Returns the credentials JSON string.
async fn complete_auth_flow(client: &reqwest::Client, input: &str, code_verifier: &str, expected_state: &str) -> Result<String, String> {
    let (auth_code, pasted_state) = match input.split_once('#') {
        Some((code, st)) => (code, st),
        None => (input, expected_state),
    };

    if pasted_state != expected_state {
        return Err("state mismatch — possible CSRF, please retry auth".into());
    }

    let body = serde_json::json!({
        "grant_type": "authorization_code",
        "code": auth_code,
        "state": pasted_state,
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": code_verifier,
    });

    let response = client.post(OAUTH_TOKEN_URL)
        .header("User-Agent", "axios/1.13.6")
        .timeout(std::time::Duration::from_secs(OAUTH_HTTP_TIMEOUT_SECS))
        .json(&body)
        .send()
        .await
        .map_err(|e| {
            if e.is_timeout() {
                format!("token exchange timed out after {OAUTH_HTTP_TIMEOUT_SECS}s")
            } else {
                format!("token exchange request failed: {e}")
            }
        })?;

    let response_str = response.text().await
        .map_err(|e| format!("failed to read token response: {e}"))?;

    let token_data: serde_json::Value = serde_json::from_str(&response_str)
        .map_err(|_| format!("token exchange failed: {}", response_str))?;

    if let Some(error) = token_data.get("error") {
        return Err(format!(
            "auth failed: {} — {}",
            error,
            token_data
                .get("error_description")
                .unwrap_or(error)
        ));
    }

    let access_token = token_data["access_token"]
        .as_str()
        .ok_or("no access_token in response")?;
    let refresh_token = token_data.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = token_data["expires_in"].as_u64().unwrap_or(DEFAULT_TOKEN_EXPIRES_SECS);

    let expires_at = crate::time_utils::now_epoch_millis() + (expires_in as u128) * 1000;

    let mut creds = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": access_token,
            "expiresAt": expires_at as u64,
        }
    });
    if let Some(rt) = refresh_token {
        creds["claudeAiOauth"]["refreshToken"] = serde_json::json!(rt);
    }
    if let Some(scopes) = token_data.get("scope").and_then(|v| v.as_str()) {
        let scope_list: Vec<&str> = scopes.split_whitespace().collect();
        creds["claudeAiOauth"]["scopes"] = serde_json::json!(scope_list);
    }

    Ok(creds.to_string())
}
