//! Claude OAuth handlers. Standalone PKCE dance: the caller gets credentials
//! back and sends them to `PUT /agents/{name}/provider` (then restarts the agent to apply).

use axum::{extract::State, http::StatusCode, Json};
use ring::rand::SecureRandom;
use serde::{Deserialize, Serialize};

use crate::state::{err_response, AuthSession, SharedState};

const OAUTH_HTTP_TIMEOUT_SECS: u64 = 30;
const DEFAULT_TOKEN_EXPIRES_SECS: u64 = 28800;

const OAUTH_CLIENT_ID: &str = "9d1c250a-e61b-44d9-88ed-5944d1962f5e";
const OAUTH_REDIRECT_URI: &str = "https://console.anthropic.com/oauth/code/callback";
const OAUTH_TOKEN_URL: &str = "https://platform.claude.com/v1/oauth/token";
const OAUTH_AUTHORIZE_URL: &str = "https://claude.ai/oauth/authorize";

const ANTHROPIC_MODELS_URL: &str = "https://api.anthropic.com/v1/models";
const ANTHROPIC_VERSION: &str = "2023-06-01";
const ANTHROPIC_OAUTH_BETA: &str = "oauth-2025-04-20";
const ANTHROPIC_AUTHOR: &str = "Anthropic";
/// The Models API paginates (default page 20); ask for its maximum so the catalog is one page.
const ANTHROPIC_MODELS_PAGE_LIMIT: &str = "1000";

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
    let session_id = hex::encode(rand::random::<[u8; 16]>());

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

    Ok(Json(OAuthStartResponse {
        auth_url,
        session_id,
    }))
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

    let credentials = complete_auth_flow(
        &state.http_client,
        &body.code,
        &session.code_verifier,
        &session.state,
    )
    .await
    .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e))?;

    Ok(Json(serde_json::json!({ "credentials": credentials })))
}

#[derive(Deserialize)]
pub struct ClaudeModelsBody {
    pub credentials: String,
}

#[derive(Serialize)]
pub struct ClaudeModel {
    pub slug: String,
    pub label: String,
    pub author: String,
}

#[derive(Deserialize)]
struct OAuthBlob {
    #[serde(rename = "claudeAiOauth")]
    claude_ai_oauth: OAuthInner,
}

#[derive(Deserialize)]
struct OAuthInner {
    #[serde(rename = "accessToken")]
    access_token: String,
}

#[derive(Deserialize)]
struct AnthropicModelsResponse {
    data: Vec<AnthropicModel>,
}

#[derive(Deserialize)]
struct AnthropicModel {
    id: String,
    display_name: String,
}

/// Pull the access token out of the browser-held OAuth blob. A blob missing
/// `claudeAiOauth.accessToken` is a client error, not an upstream one.
fn parse_oauth_access_token(credentials: &str) -> Result<String, (StatusCode, Json<serde_json::Value>)> {
    let blob: OAuthBlob = serde_json::from_str(credentials).map_err(|_| {
        err_response(
            StatusCode::BAD_REQUEST,
            "credentials blob is not valid claude oauth json",
        )
    })?;
    Ok(blob.claude_ai_oauth.access_token)
}

/// Lists the account's Claude models from the Anthropic Models API, authenticated with the
/// browser-held OAuth token. Onboarding uses this before the agent is signed in.
pub async fn list_models_handler(
    State(state): State<SharedState>,
    Json(body): Json<ClaudeModelsBody>,
) -> Result<Json<Vec<ClaudeModel>>, (StatusCode, Json<serde_json::Value>)> {
    let access_token = parse_oauth_access_token(&body.credentials)?;
    let models = fetch_claude_models(&state.http_client, &access_token).await?;
    Ok(Json(models))
}

/// Calls the Anthropic Models API with the browser-held OAuth token and maps its
/// response into the shape the onboarding model picker reads.
async fn fetch_claude_models(
    client: &reqwest::Client,
    access_token: &str,
) -> Result<Vec<ClaudeModel>, (StatusCode, Json<serde_json::Value>)> {
    let resp = client
        .get(ANTHROPIC_MODELS_URL)
        .query(&[("limit", ANTHROPIC_MODELS_PAGE_LIMIT)])
        .bearer_auth(access_token)
        .header("anthropic-version", ANTHROPIC_VERSION)
        .header("anthropic-beta", ANTHROPIC_OAUTH_BETA)
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("anthropic request failed: {e}"),
            )
        })?;
    if resp.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(err_response(
            StatusCode::BAD_REQUEST,
            "claude credentials rejected by anthropic",
        ));
    }
    if !resp.status().is_success() {
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("anthropic returned HTTP {}", resp.status()),
        ));
    }
    let parsed: AnthropicModelsResponse = resp.json().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("anthropic response parse failed: {e}"),
        )
    })?;
    Ok(parsed
        .data
        .into_iter()
        .map(|m| ClaudeModel {
            slug: m.id,
            label: m.display_name,
            author: ANTHROPIC_AUTHOR.to_string(),
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::parse_oauth_access_token;
    use axum::http::StatusCode;

    #[test]
    fn claude_models_rejects_blob_without_access_token() {
        // A credentials blob missing claudeAiOauth.accessToken is a client error.
        let err = parse_oauth_access_token("{\"claudeAiOauth\":{}}")
            .expect_err("blob without accessToken should be rejected");
        assert_eq!(err.0, StatusCode::BAD_REQUEST);
    }
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

/// Start the OAuth PKCE flow. Returns (`auth_url`, `code_verifier`, state).
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
async fn complete_auth_flow(
    client: &reqwest::Client,
    input: &str,
    code_verifier: &str,
    expected_state: &str,
) -> Result<String, String> {
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

    let response = client
        .post(OAUTH_TOKEN_URL)
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

    let response_str = response
        .text()
        .await
        .map_err(|e| format!("failed to read token response: {e}"))?;

    let token_data: serde_json::Value = serde_json::from_str(&response_str)
        .map_err(|_| format!("token exchange failed: {response_str}"))?;

    if let Some(error) = token_data.get("error") {
        return Err(format!(
            "auth failed: {} — {}",
            error,
            token_data.get("error_description").unwrap_or(error)
        ));
    }

    let access_token = token_data["access_token"]
        .as_str()
        .ok_or("no access_token in response")?;
    let refresh_token = token_data.get("refresh_token").and_then(|v| v.as_str());
    let expires_in = token_data["expires_in"]
        .as_u64()
        .unwrap_or(DEFAULT_TOKEN_EXPIRES_SECS);

    let expires_at = crate::time_utils::now_epoch_millis() + u128::from(expires_in) * 1000;

    let mut creds = serde_json::json!({
        "claudeAiOauth": {
            "accessToken": access_token,
            "expiresAt": u64::try_from(expires_at).unwrap_or(u64::MAX),
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
