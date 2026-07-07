//! Claude OAuth handlers. Standalone PKCE dance: the caller gets credentials
//! back and sends them to `PUT /agents/{name}/provider` (then restarts the agent to apply).

use axum::{Json, extract::State, http::StatusCode};
use serde::{Deserialize, Serialize};

use crate::auth;
use crate::docker;
use crate::serve::{SharedState, err_response};

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
    let (auth_url, code_verifier, auth_state) = docker::start_auth_flow();
    let session_id: String = (0..16)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect();

    state.clean_expired_sessions().await;

    let mut sessions = state.auth_sessions.lock().await;
    sessions.insert(
        session_id.clone(),
        auth::AuthSession {
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

    let credentials = docker::complete_auth_flow(&state.http_client, &body.code, &session.code_verifier, &session.state)
        .await
        .map_err(|e| err_response(StatusCode::BAD_REQUEST, &e.to_string()))?;

    Ok(Json(serde_json::json!({ "credentials": credentials })))
}
