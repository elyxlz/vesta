//! Standalone `ChatGPT` device OAuth. The returned refreshable credential blob is passed to an
//! agent's `PUT /provider`, where the pinned local bridge owns subsequent refreshes.

use axum::{extract::State, http::StatusCode, Json};
use base64::Engine;
use serde::{Deserialize, Serialize};

use crate::state::{err_response, OpenAiAuthSession, SharedState};

const CLIENT_ID: &str = "app_EMoamEEZ73f0CkXaXp7hrann";
const ISSUER: &str = "https://auth.openai.com";
const HTTP_TIMEOUT_SECS: u64 = 30;

#[derive(Deserialize)]
struct DeviceInit {
    device_auth_id: String,
    user_code: String,
}

#[derive(Deserialize)]
struct DevicePoll {
    authorization_code: String,
    code_verifier: String,
}

#[derive(Deserialize)]
struct TokenResponse {
    id_token: Option<String>,
    access_token: String,
    refresh_token: String,
    expires_in: Option<u64>,
}

#[derive(Serialize)]
pub struct OAuthStartResponse {
    pub auth_url: String,
    pub user_code: String,
    pub session_id: String,
}

#[derive(Deserialize)]
pub struct OAuthCompleteBody {
    pub session_id: String,
}

pub async fn oauth_start_handler(
    State(state): State<SharedState>,
) -> Result<Json<OAuthStartResponse>, (StatusCode, Json<serde_json::Value>)> {
    state.clean_expired_sessions().await;
    let response = state
        .http_client
        .post(format!("{ISSUER}/api/accounts/deviceauth/usercode"))
        .timeout(std::time::Duration::from_secs(HTTP_TIMEOUT_SECS))
        .json(&serde_json::json!({ "client_id": CLIENT_ID }))
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("device login start failed: {e}"),
            )
        })?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().await.unwrap_or_default();
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("OpenAI returned {status}: {body}"),
        ));
    }
    let init: DeviceInit = response.json().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("invalid device login response: {e}"),
        )
    })?;
    let session_id = hex::encode(rand::random::<[u8; 16]>());
    state.openai_auth_sessions.lock().await.insert(
        session_id.clone(),
        OpenAiAuthSession {
            device_auth_id: init.device_auth_id,
            user_code: init.user_code.clone(),
            created: std::time::Instant::now(),
        },
    );
    Ok(Json(OAuthStartResponse {
        auth_url: format!("{ISSUER}/codex/device"),
        user_code: init.user_code,
        session_id,
    }))
}

pub async fn oauth_complete_handler(
    State(state): State<SharedState>,
    Json(body): Json<OAuthCompleteBody>,
) -> Result<Json<serde_json::Value>, (StatusCode, Json<serde_json::Value>)> {
    state.clean_expired_sessions().await;
    let session = state
        .openai_auth_sessions
        .lock()
        .await
        .get(&body.session_id)
        .cloned()
        .ok_or_else(|| {
            err_response(
                StatusCode::BAD_REQUEST,
                "invalid or expired OpenAI auth session",
            )
        })?;
    let response = state
        .http_client
        .post(format!("{ISSUER}/api/accounts/deviceauth/token"))
        .timeout(std::time::Duration::from_secs(HTTP_TIMEOUT_SECS))
        .json(&serde_json::json!({
            "device_auth_id": session.device_auth_id,
            "user_code": session.user_code,
        }))
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("device login check failed: {e}"),
            )
        })?;
    if response.status() == reqwest::StatusCode::FORBIDDEN
        || response.status() == reqwest::StatusCode::NOT_FOUND
    {
        return Err(err_response(
            StatusCode::CONFLICT,
            "authorization is still pending",
        ));
    }
    let status = response.status();
    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("OpenAI returned {status}: {text}"),
        ));
    }
    let poll: DevicePoll = response.json().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("invalid device login response: {e}"),
        )
    })?;
    let redirect_uri = format!("{ISSUER}/deviceauth/callback");
    let response = state
        .http_client
        .post(format!("{ISSUER}/oauth/token"))
        .timeout(std::time::Duration::from_secs(HTTP_TIMEOUT_SECS))
        .form(&[
            ("grant_type", "authorization_code"),
            ("code", poll.authorization_code.as_str()),
            ("redirect_uri", redirect_uri.as_str()),
            ("client_id", CLIENT_ID),
            ("code_verifier", poll.code_verifier.as_str()),
        ])
        .send()
        .await
        .map_err(|e| {
            err_response(
                StatusCode::BAD_GATEWAY,
                &format!("token exchange failed: {e}"),
            )
        })?;
    let status = response.status();
    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            &format!("OpenAI returned {status}: {text}"),
        ));
    }
    let tokens: TokenResponse = response.json().await.map_err(|e| {
        err_response(
            StatusCode::BAD_GATEWAY,
            &format!("invalid token response: {e}"),
        )
    })?;
    if tokens.access_token.trim().is_empty()
        || tokens.refresh_token.trim().is_empty()
        || tokens.expires_in == Some(0)
    {
        return Err(err_response(
            StatusCode::BAD_GATEWAY,
            "OpenAI returned incomplete credentials",
        ));
    }
    state
        .openai_auth_sessions
        .lock()
        .await
        .remove(&body.session_id);
    let expires = crate::time_utils::now_epoch_millis()
        .saturating_add(u128::from(tokens.expires_in.unwrap_or(3600)).saturating_mul(1000));
    let account_id = tokens
        .id_token
        .as_deref()
        .and_then(account_id_from_jwt)
        .or_else(|| account_id_from_jwt(&tokens.access_token));
    let credentials = serde_json::json!({
        "access": tokens.access_token,
        "refresh": tokens.refresh_token,
        "expires": u64::try_from(expires).unwrap_or(u64::MAX),
        "accountId": account_id,
    });
    Ok(Json(
        serde_json::json!({ "credentials": credentials.to_string() }),
    ))
}

fn account_id_from_jwt(token: &str) -> Option<String> {
    let payload = token.split('.').nth(1)?;
    let decoded = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .decode(payload)
        .ok()?;
    let claims: serde_json::Value = serde_json::from_slice(&decoded).ok()?;
    claims
        .get("chatgpt_account_id")
        .or_else(|| claims.get("https://api.openai.com/auth.chatgpt_account_id"))
        .and_then(serde_json::Value::as_str)
        .map(str::to_owned)
        .or_else(|| {
            claims
                .get("https://api.openai.com/auth")?
                .get("chatgpt_account_id")?
                .as_str()
                .map(str::to_owned)
        })
        .or_else(|| {
            claims
                .get("organizations")?
                .as_array()?
                .first()?
                .get("id")?
                .as_str()
                .map(str::to_owned)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn jwt(claims: &serde_json::Value) -> String {
        let payload = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(claims.to_string());
        format!("header.{payload}.signature")
    }

    #[test]
    fn extracts_direct_chatgpt_account_id() {
        let token = jwt(&serde_json::json!({ "chatgpt_account_id": "acct_direct" }));
        assert_eq!(account_id_from_jwt(&token).as_deref(), Some("acct_direct"));
    }

    #[test]
    fn extracts_nested_chatgpt_account_id() {
        let token = jwt(&serde_json::json!({
            "https://api.openai.com/auth": { "chatgpt_account_id": "acct_nested" }
        }));
        assert_eq!(account_id_from_jwt(&token).as_deref(), Some("acct_nested"));
    }

    #[test]
    fn rejects_malformed_jwt() {
        assert_eq!(account_id_from_jwt("not-a-jwt"), None);
    }
}
