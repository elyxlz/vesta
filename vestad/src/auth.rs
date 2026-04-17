use axum::{
    extract::{Request, State},
    http::{HeaderMap, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};

use crate::jwt;
use crate::serve::SharedState;

const AUTH_SESSION_TIMEOUT_SECS: u64 = 600;

pub(crate) struct AuthSession {
    pub code_verifier: String,
    pub state: String,
    pub created: std::time::Instant,
}

impl AuthSession {
    pub fn is_expired(&self) -> bool {
        self.created.elapsed().as_secs() > AUTH_SESSION_TIMEOUT_SECS
    }
}

pub async fn auth_middleware(
    State(state): State<SharedState>,
    headers: HeaderMap,
    request: Request,
    next: Next,
) -> Response {
    if request.method() == axum::http::Method::OPTIONS {
        return next.run(request).await;
    }

    if has_valid_api_auth(&headers, request.uri(), &state.api_key) {
        return next.run(request).await;
    }

    let path = request.uri().path().to_string();
    tracing::warn!(path = %path, "client auth failed");
    (StatusCode::UNAUTHORIZED, Json(serde_json::json!({"error": "unauthorized"}))).into_response()
}

/// Requires the agent's own token via X-Agent-Token header.
/// The agent name is extracted from the path `/agents/{name}/...`.
pub async fn auth_middleware_agent_token(
    State(state): State<SharedState>,
    headers: HeaderMap,
    request: Request,
    next: Next,
) -> Response {
    if request.method() == axum::http::Method::OPTIONS {
        return next.run(request).await;
    }

    let path = request.uri().path().to_string();
    let Some(agent_name) = extract_agent_name(&path) else {
        tracing::warn!(path = %path, reason = "path-missing-agent-name", "agent token auth failed");
        return unauthorized();
    };

    let provided = headers.get("x-agent-token").and_then(|v| v.to_str().ok());
    let Some(provided) = provided else {
        tracing::warn!(
            path = %path,
            agent = %agent_name,
            reason = "header-missing",
            "agent token auth failed",
        );
        return unauthorized();
    };

    let (_, expected) = crate::docker::read_agent_port_and_token(&agent_name, &state.env_config.agents_dir);
    let Some(expected) = expected else {
        tracing::warn!(
            path = %path,
            agent = %agent_name,
            reason = "env-file-missing-or-no-token",
            agents_dir = %state.env_config.agents_dir.display(),
            "agent token auth failed",
        );
        return unauthorized();
    };

    if provided == expected {
        return next.run(request).await;
    }

    tracing::warn!(
        path = %path,
        agent = %agent_name,
        reason = "token-mismatch",
        provided_fp = %token_fingerprint(provided),
        expected_fp = %token_fingerprint(&expected),
        provided_len = provided.len(),
        expected_len = expected.len(),
        "agent token auth failed",
    );
    unauthorized()
}

fn unauthorized() -> Response {
    (StatusCode::UNAUTHORIZED, Json(serde_json::json!({
        "error": "unauthorized — pass X-Agent-Token header with the AGENT_TOKEN from the agent's environment"
    }))).into_response()
}

/// Short, non-reversible fingerprint of a token for diagnostic logs.
/// Returns the first 6 hex chars of its SHA-256 — enough to tell two tokens
/// apart without leaking the secret itself.
fn token_fingerprint(token: &str) -> String {
    let digest = ring::digest::digest(&ring::digest::SHA256, token.as_bytes());
    let mut out = String::with_capacity(6);
    for byte in digest.as_ref().iter().take(3) {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

pub(crate) fn has_valid_api_auth(headers: &HeaderMap, uri: &axum::http::Uri, api_key: &str) -> bool {
    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token| verify_token(token, api_key))
        .unwrap_or(false);
    if bearer_ok {
        return true;
    }
    uri.query()
        .and_then(|q| q.split('&').find_map(|p| p.strip_prefix("token=")))
        .map(|t| verify_token(t, api_key))
        .unwrap_or(false)
}

fn extract_agent_name(path: &str) -> Option<String> {
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').collect();
    if parts.len() >= 2 && parts[0] == "agents" {
        Some(parts[1].to_string())
    } else {
        None
    }
}


/// Accept raw API key or JWT access token.
pub(crate) fn verify_token(token: &str, api_key: &str) -> bool {
    if token == api_key {
        return true;
    }
    if token.contains('.') {
        return jwt::validate_token(api_key, token, "access").is_ok();
    }
    false
}

// --- Session endpoints ---

#[derive(Deserialize)]
pub struct SessionRequest {
    api_key: String,
}

#[derive(Serialize)]
pub struct SessionResponse {
    access_token: String,
    refresh_token: String,
    expires_in: u64,
}

#[derive(Deserialize)]
pub struct RefreshRequest {
    refresh_token: String,
}

pub async fn create_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<SessionRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    if body.api_key != state.api_key {
        tracing::warn!("client session auth failed: invalid API key");
        return Err(crate::serve::err_response(StatusCode::UNAUTHORIZED, "invalid API key"));
    }

    tracing::info!("client connected (new session)");
    Ok(Json(SessionResponse {
        access_token: jwt::create_token(&state.api_key, "access", jwt::ACCESS_TOKEN_TTL),
        refresh_token: jwt::create_token(&state.api_key, "refresh", jwt::REFRESH_TOKEN_TTL),
        expires_in: jwt::ACCESS_TOKEN_TTL,
    }))
}

pub async fn refresh_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<RefreshRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    jwt::validate_token(&state.api_key, &body.refresh_token, "refresh")
        .map_err(|e| crate::serve::err_response(StatusCode::UNAUTHORIZED, &e.to_string()))?;

    Ok(Json(SessionResponse {
        access_token: jwt::create_token(&state.api_key, "access", jwt::ACCESS_TOKEN_TTL),
        refresh_token: jwt::create_token(&state.api_key, "refresh", jwt::REFRESH_TOKEN_TTL),
        expires_in: jwt::ACCESS_TOKEN_TTL,
    }))
}
