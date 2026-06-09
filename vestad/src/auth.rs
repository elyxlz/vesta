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

    if check_agent_token(&headers, &agent_name, &state, &path) {
        return next.run(request).await;
    }
    unauthorized()
}

/// Accepts either the API key (Authorization: Bearer / ?token=) or the agent's
/// own X-Agent-Token. Used for read-only routes the web/CLI clients and the
/// agent itself both want to call.
pub async fn auth_middleware_api_or_agent_token(
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
    if let Some(agent_name) = extract_agent_name(&path) {
        if check_agent_token(&headers, &agent_name, &state, &path) {
            return next.run(request).await;
        }
    }
    tracing::warn!(path = %path, "client auth failed (neither api-key nor agent-token accepted)");
    unauthorized()
}

fn check_agent_token(headers: &HeaderMap, agent_name: &str, state: &SharedState, path: &str) -> bool {
    let Some(provided) = headers.get("x-agent-token").and_then(|v| v.to_str().ok()) else {
        tracing::warn!(path = %path, agent = %agent_name, reason = "header-missing", "agent token auth failed");
        return false;
    };

    let (_, expected) = crate::docker::read_agent_port_and_token(agent_name, &state.env_config.agents_dir);
    let Some(expected) = expected else {
        tracing::warn!(
            path = %path,
            agent = %agent_name,
            reason = "env-file-missing-or-no-token",
            agents_dir = %state.env_config.agents_dir.display(),
            "agent token auth failed",
        );
        return false;
    };

    if provided == expected {
        return true;
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
    false
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

/// 16 random bytes as hex — a refresh-token id or family id.
fn rand_id() -> String {
    (0..16).map(|_| format!("{:02x}", rand::random::<u8>())).collect()
}

/// The live refresh-token registry: `jti` → family id. (`AppState.refresh_live`.)
type RefreshLive = tokio::sync::Mutex<std::collections::HashMap<String, String>>;

/// Start a new refresh-token family: register a fresh `jti` and return `(jti, fam)`
/// for minting the first refresh token of a login.
async fn register_refresh_family(live: &RefreshLive) -> (String, String) {
    let (jti, fam) = (rand_id(), rand_id());
    live.lock().await.insert(jti.clone(), fam.clone());
    (jti, fam)
}

/// Rotate a presented refresh token (RFC 9700 §2.2.2/§4.14). If its `jti` is the
/// live one for its family, consume it and return the next `(jti, fam)`. Otherwise
/// (an unknown/already-spent `jti` — reuse, replay, or a legacy non-rotating
/// token) return None AND revoke the entire family, so a stolen-and-replayed token
/// invalidates the chain regardless of who refreshes first.
async fn rotate_refresh(live: &RefreshLive, claims: &jwt::Claims) -> Option<(String, String)> {
    let (Some(jti), Some(fam)) = (claims.jti.as_ref(), claims.fam.as_ref()) else {
        return None;
    };
    let mut live = live.lock().await;
    if live.get(jti) == Some(fam) {
        live.remove(jti);
        let new_jti = rand_id();
        live.insert(new_jti.clone(), fam.clone());
        Some((new_jti, fam.clone()))
    } else {
        live.retain(|_, f| f != fam);
        None
    }
}

/// Build a session response minting a fresh access token + the next rotating
/// refresh token for `(jti, fam)`.
fn session_response(api_key: &str, jti: &str, fam: &str) -> SessionResponse {
    SessionResponse {
        access_token: jwt::create_token(api_key, "access", jwt::ACCESS_TOKEN_TTL),
        refresh_token: jwt::create_refresh_token(api_key, jti, fam),
        expires_in: jwt::ACCESS_TOKEN_TTL,
    }
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
    let (jti, fam) = register_refresh_family(&state.refresh_live).await;
    Ok(Json(session_response(&state.api_key, &jti, &fam)))
}

/// `POST /auth/exchange` — runs behind `auth_middleware`, so the caller already
/// proved a valid access token (or api_key). Used by the hosted (vesta.run) native
/// apps: after the OAuth handoff they hold a control-plane-minted access token, and
/// exchange it here for a REGISTERED rotating refresh token. vestad never mints a
/// refresh token for an unauthenticated caller, and the control plane never mints a
/// (non-rotating) refresh token at all.
pub async fn exchange_session_handler(
    State(state): State<SharedState>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    tracing::info!("issued a rotating refresh token (hosted exchange)");
    let (jti, fam) = register_refresh_family(&state.refresh_live).await;
    Ok(Json(session_response(&state.api_key, &jti, &fam)))
}

pub async fn refresh_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<RefreshRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    let claims = jwt::validate_token(&state.api_key, &body.refresh_token, "refresh")
        .map_err(|e| crate::serve::err_response(StatusCode::UNAUTHORIZED, &e.to_string()))?;

    match rotate_refresh(&state.refresh_live, &claims).await {
        Some((jti, fam)) => Ok(Json(session_response(&state.api_key, &jti, &fam))),
        None => Err(crate::serve::err_response(
            StatusCode::UNAUTHORIZED,
            "refresh token revoked or reused",
        )),
    }
}

#[cfg(test)]
mod refresh_rotation_tests {
    use super::*;

    fn refresh_claims(jti: &str, fam: &str) -> jwt::Claims {
        jwt::Claims {
            sub: "vesta-app".into(),
            typ: "refresh".into(),
            iat: 0,
            exp: u64::MAX,
            jti: Some(jti.into()),
            fam: Some(fam.into()),
        }
    }

    fn empty() -> RefreshLive {
        tokio::sync::Mutex::new(std::collections::HashMap::new())
    }

    #[tokio::test]
    async fn happy_path_chains_indefinitely() {
        let live = empty();
        let (mut jti, fam) = register_refresh_family(&live).await;
        for _ in 0..5 {
            let (next, f) = rotate_refresh(&live, &refresh_claims(&jti, &fam))
                .await
                .expect("a live token rotates");
            assert_eq!(f, fam);
            assert_ne!(next, jti);
            jti = next;
        }
        // Exactly one live token remains after a chain of rotations.
        assert_eq!(live.lock().await.len(), 1);
    }

    #[tokio::test]
    async fn replaying_a_spent_token_revokes_the_whole_family() {
        let live = empty();
        let (jti0, fam) = register_refresh_family(&live).await;
        let claims0 = refresh_claims(&jti0, &fam);

        // First use rotates fine, yielding the next token.
        let (jti1, _) = rotate_refresh(&live, &claims0).await.expect("first use ok");

        // Replaying the now-spent token is reuse -> None, AND kills the family.
        assert!(rotate_refresh(&live, &claims0).await.is_none());

        // So even the legit *next* token is dead now (chain invalidated).
        assert!(rotate_refresh(&live, &refresh_claims(&jti1, &fam))
            .await
            .is_none());
        assert!(live.lock().await.is_empty());
    }

    #[tokio::test]
    async fn legacy_token_without_jti_is_rejected() {
        let live = empty();
        let claims = jwt::Claims {
            sub: "vesta-app".into(),
            typ: "refresh".into(),
            iat: 0,
            exp: u64::MAX,
            jti: None,
            fam: None,
        };
        assert!(rotate_refresh(&live, &claims).await.is_none());
    }

    #[tokio::test]
    async fn unknown_jti_or_family_is_rejected() {
        let live = empty();
        let (jti, _fam) = register_refresh_family(&live).await;
        // Right jti, wrong family.
        assert!(rotate_refresh(&live, &refresh_claims(&jti, "wrongfam"))
            .await
            .is_none());
        // Entirely unknown.
        assert!(rotate_refresh(&live, &refresh_claims("nope", "nofam"))
            .await
            .is_none());
    }

    #[tokio::test]
    async fn two_families_are_independent() {
        let live = empty();
        let (a0, fam_a) = register_refresh_family(&live).await;
        let (b0, fam_b) = register_refresh_family(&live).await;
        // Reuse-revoke family A by replaying its first token after rotating it.
        let _ = rotate_refresh(&live, &refresh_claims(&a0, &fam_a)).await.unwrap();
        assert!(rotate_refresh(&live, &refresh_claims(&a0, &fam_a)).await.is_none());
        // Family B is untouched and still rotates.
        assert!(rotate_refresh(&live, &refresh_claims(&b0, &fam_b)).await.is_some());
    }
}
