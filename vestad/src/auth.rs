use axum::{
    extract::{ConnectInfo, Request, State},
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
    check_auth(state, None, headers, request, next).await
}

/// Like `auth_middleware` but allows unauthenticated access from localhost
/// (agent containers registering services).
pub async fn auth_middleware_localhost(
    State(state): State<SharedState>,
    connect_info: ConnectInfo<std::net::SocketAddr>,
    headers: HeaderMap,
    request: Request,
    next: Next,
) -> Response {
    check_auth(state, Some(connect_info), headers, request, next).await
}

async fn check_auth(
    state: SharedState,
    connect_info: Option<ConnectInfo<std::net::SocketAddr>>,
    headers: HeaderMap,
    request: Request,
    next: Next,
) -> Response {
    if request.method() == axum::http::Method::OPTIONS {
        return next.run(request).await;
    }

    if let Some(ci) = connect_info {
        if ci.0.ip().is_loopback() {
            return next.run(request).await;
        }
    }

    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|token| verify_token(token, &state.api_key))
        .unwrap_or(false);

    let query_ok = if !bearer_ok {
        request
            .uri()
            .query()
            .and_then(|q| {
                q.split('&')
                    .find_map(|p| p.strip_prefix("token="))
            })
            .map(|t| verify_token(t, &state.api_key))
            .unwrap_or(false)
    } else {
        false
    };

    if !bearer_ok && !query_ok {
        let path = request.uri().path().to_string();
        tracing::warn!(path = %path, "client auth failed");
        return (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "unauthorized"})),
        )
            .into_response();
    }

    next.run(request).await
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
