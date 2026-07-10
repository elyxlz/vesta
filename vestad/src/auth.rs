use axum::{
    extract::{Request, State},
    http::{HeaderMap, StatusCode},
    middleware::Next,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::jwt;
use crate::state::{persist_refresh_live, prune_expired, RefreshFamily, SharedState};

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
    (
        StatusCode::UNAUTHORIZED,
        Json(serde_json::json!({"error": "unauthorized"})),
    )
        .into_response()
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

fn check_agent_token(
    headers: &HeaderMap,
    agent_name: &str,
    state: &SharedState,
    path: &str,
) -> bool {
    let Some(provided) = headers.get("x-agent-token").and_then(|v| v.to_str().ok()) else {
        tracing::warn!(path = %path, agent = %agent_name, reason = "header-missing", "agent token auth failed");
        return false;
    };

    let (_, expected) =
        crate::docker::read_agent_port_and_token(agent_name, &state.env_config.agents_dir);
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
    hex::encode(&digest.as_ref()[..3])
}

pub(crate) fn has_valid_api_auth(
    headers: &HeaderMap,
    uri: &axum::http::Uri,
    api_key: &str,
) -> bool {
    let bearer_ok = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .is_some_and(|token| verify_token(token, api_key));
    let query_ok = uri
        .query()
        .and_then(|q| q.split('&').find_map(|p| p.strip_prefix("token=")))
        .is_some_and(|token| verify_token(token, api_key));
    bearer_ok || query_ok
}

fn extract_agent_name(path: &str) -> Option<String> {
    let parts: Vec<&str> = path.trim_start_matches('/').split('/').collect();
    if parts.len() >= 2 && parts[0] == "agents" {
        Some(parts[1].to_string())
    } else {
        None
    }
}

/// Constant-time byte comparison so a mismatched raw API key can't be brute-forced
/// via response-timing (the key never rotates and gates the tunnel-exposed listener).
fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |diff, (x, y)| diff | (x ^ y)) == 0
}

/// Accept raw API key or JWT access token.
pub(crate) fn verify_token(token: &str, api_key: &str) -> bool {
    if constant_time_eq(token.as_bytes(), api_key.as_bytes()) {
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
    (0..16)
        .map(|_| format!("{:02x}", rand::random::<u8>()))
        .collect()
}

/// Start a new family; returns `(jti, fam)` to mint the first refresh token with.
/// Pure (no I/O/lock) so it's unit-testable; the async wrapper locks + persists.
fn register_family(map: &mut HashMap<String, RefreshFamily>, now: u64) -> (String, String) {
    prune_expired(map, now);
    let (jti, fam) = (rand_id(), rand_id());
    map.insert(
        fam.clone(),
        RefreshFamily {
            live: jti.clone(),
            prev: None,
            exp: now + jwt::REFRESH_TOKEN_TTL,
        },
    );
    (jti, fam)
}

/// Rotate a presented refresh token (RFC 9700 §2.2.2/§4.14). Returns the `(jti, fam)`
/// to mint the next token with, or None to reject. Pure (testable):
///   - jti == family.live: advance (prev := old live, live := new), return the new jti.
///   - jti == family.prev: a retry of the just-superseded token — return the CURRENT
///     live jti again WITHOUT advancing (idempotent, no revoke).
///   - anything else for a known family: reuse/replay → REVOKE the whole family.
///   - unknown/expired/legacy (no jti/fam): None (nothing to revoke).
fn rotate(
    map: &mut HashMap<String, RefreshFamily>,
    claims: &jwt::Claims,
    now: u64,
) -> Option<(String, String)> {
    prune_expired(map, now);
    let jti = claims.jti.as_deref()?;
    let fam = claims.fam.as_deref()?;
    // Snapshot the small strings so we don't hold a borrow across the mutation.
    let (live, prev) = map.get(fam).map(|f| (f.live.clone(), f.prev.clone()))?;
    if live == jti {
        let new_jti = rand_id();
        let f = map.get_mut(fam).expect("family present");
        f.prev = Some(std::mem::replace(&mut f.live, new_jti.clone()));
        f.exp = now + jwt::REFRESH_TOKEN_TTL; // slide the idle window
        Some((new_jti, fam.to_string()))
    } else if prev.as_deref() == Some(jti) {
        // Retry grace: re-mint current, don't advance. Slide too — the re-minted
        // token's own exp is now + TTL, so the family must outlive it.
        map.get_mut(fam).expect("family present").exp = now + jwt::REFRESH_TOKEN_TTL;
        Some((live, fam.to_string()))
    } else {
        map.remove(fam); // reuse/replay → revoke the family
        None
    }
}

/// Lock + register a new family, then persist. Returns `(jti, fam)`.
async fn register_refresh_family(state: &SharedState) -> (String, String) {
    let now = crate::time_utils::now_epoch_secs();
    let mut map = state.refresh_live.lock().await;
    let res = register_family(&mut map, now);
    persist_refresh_live(&state.env_config.config_dir, &map).await;
    res
}

/// Lock + rotate, then persist. None → reject the refresh.
async fn rotate_refresh(state: &SharedState, claims: &jwt::Claims) -> Option<(String, String)> {
    let now = crate::time_utils::now_epoch_secs();
    let mut map = state.refresh_live.lock().await;
    let res = rotate(&mut map, claims, now);
    persist_refresh_live(&state.env_config.config_dir, &map).await;
    res
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
        return Err(crate::state::err_response(StatusCode::UNAUTHORIZED, "invalid API key"));
    }

    tracing::info!("client connected (new session)");
    let (jti, fam) = register_refresh_family(&state).await;
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
    let (jti, fam) = register_refresh_family(&state).await;
    Ok(Json(session_response(&state.api_key, &jti, &fam)))
}

pub async fn refresh_session_handler(
    State(state): State<SharedState>,
    Json(body): Json<RefreshRequest>,
) -> Result<Json<SessionResponse>, (StatusCode, Json<serde_json::Value>)> {
    let claims = jwt::validate_token(&state.api_key, &body.refresh_token, "refresh")
        .map_err(|e| crate::state::err_response(StatusCode::UNAUTHORIZED, &e.to_string()))?;

    match rotate_refresh(&state, &claims).await {
        Some((jti, fam)) => Ok(Json(session_response(&state.api_key, &jti, &fam))),
        None => Err(crate::state::err_response(
            StatusCode::UNAUTHORIZED,
            "refresh token revoked or reused",
        )),
    }
}

#[cfg(test)]
mod refresh_rotation_tests {
    use super::*;

    const NOW: u64 = 1_000_000;

    fn refresh_claims(jti: &str, fam: &str) -> jwt::Claims {
        jwt::Claims {
            sub: "vesta-app".into(),
            typ: "refresh".into(),
            iat: NOW,
            exp: NOW + jwt::REFRESH_TOKEN_TTL,
            jti: Some(jti.into()),
            fam: Some(fam.into()),
        }
    }

    #[test]
    fn happy_path_chains_indefinitely() {
        let mut map = HashMap::new();
        let (mut jti, fam) = register_family(&mut map, NOW);
        for _ in 0..5 {
            let (next, f) =
                rotate(&mut map, &refresh_claims(&jti, &fam), NOW).expect("live rotates");
            assert_eq!(f, fam);
            assert_ne!(next, jti);
            jti = next;
        }
        // One family, updated in place — the map does not grow per rotation.
        assert_eq!(map.len(), 1);
    }

    #[test]
    fn retry_of_the_prev_token_is_idempotent_grace() {
        let mut map = HashMap::new();
        let (jti0, fam) = register_family(&mut map, NOW);
        let (jti1, _) = rotate(&mut map, &refresh_claims(&jti0, &fam), NOW).expect("0->1");
        // A retry presenting the just-superseded jti0 returns the CURRENT live (jti1)
        // WITHOUT advancing or revoking — a dropped-response retry isn't a logout.
        let (again, _) = rotate(&mut map, &refresh_claims(&jti0, &fam), NOW).expect("grace");
        assert_eq!(again, jti1);
        assert_eq!(map.len(), 1);
        // jti1 still rotates normally afterward.
        assert!(rotate(&mut map, &refresh_claims(&jti1, &fam), NOW).is_some());
    }

    #[test]
    fn reuse_of_a_two_step_old_token_revokes_the_family() {
        let mut map = HashMap::new();
        let (jti0, fam) = register_family(&mut map, NOW);
        let (jti1, _) = rotate(&mut map, &refresh_claims(&jti0, &fam), NOW).expect("0->1");
        let (jti2, _) = rotate(&mut map, &refresh_claims(&jti1, &fam), NOW).expect("1->2");
        // jti0 is now two steps back (neither live=jti2 nor prev=jti1) → reuse → revoke.
        assert!(rotate(&mut map, &refresh_claims(&jti0, &fam), NOW).is_none());
        assert!(map.is_empty());
        // The whole chain is dead, including what was live.
        assert!(rotate(&mut map, &refresh_claims(&jti2, &fam), NOW).is_none());
    }

    #[test]
    fn legacy_token_without_jti_is_rejected() {
        let mut map = HashMap::new();
        let claims = jwt::Claims {
            sub: "vesta-app".into(),
            typ: "refresh".into(),
            iat: NOW,
            exp: NOW + 1,
            jti: None,
            fam: None,
        };
        assert!(rotate(&mut map, &claims, NOW).is_none());
    }

    #[test]
    fn unknown_family_is_rejected_without_panicking() {
        let mut map = HashMap::new();
        assert!(rotate(&mut map, &refresh_claims("nope", "nofam"), NOW).is_none());
    }

    #[test]
    fn rotation_slides_the_family_expiry() {
        let mut map = HashMap::new();
        let (jti0, fam) = register_family(&mut map, NOW);
        // Rotate just before the original expiry...
        let almost_expired = NOW + jwt::REFRESH_TOKEN_TTL - 1;
        let (jti1, _) =
            rotate(&mut map, &refresh_claims(&jti0, &fam), almost_expired).expect("live rotates");
        // ...and the family survives past it: the expiry is an idle window, not
        // an absolute clock started at login.
        let past_original_expiry = NOW + jwt::REFRESH_TOKEN_TTL + 1;
        assert!(rotate(&mut map, &refresh_claims(&jti1, &fam), past_original_expiry).is_some());
    }

    #[test]
    fn retry_grace_slides_the_family_expiry() {
        let mut map = HashMap::new();
        let (jti0, fam) = register_family(&mut map, NOW);
        let _ = rotate(&mut map, &refresh_claims(&jti0, &fam), NOW).expect("0->1");
        // A grace retry of jti0 just before expiry re-mints the live token, whose
        // own exp is now + TTL — the family must slide to outlive it.
        let almost_expired = NOW + jwt::REFRESH_TOKEN_TTL - 1;
        let (live, _) =
            rotate(&mut map, &refresh_claims(&jti0, &fam), almost_expired).expect("grace");
        let past_original_expiry = NOW + jwt::REFRESH_TOKEN_TTL + 1;
        assert!(rotate(&mut map, &refresh_claims(&live, &fam), past_original_expiry).is_some());
    }

    #[test]
    fn expired_family_is_pruned_and_rejected() {
        let mut map = HashMap::new();
        let (jti, fam) = register_family(&mut map, NOW);
        let later = NOW + jwt::REFRESH_TOKEN_TTL + 1; // past the family exp
        assert!(rotate(&mut map, &refresh_claims(&jti, &fam), later).is_none());
        assert!(map.is_empty()); // pruned
    }

    #[test]
    fn two_families_are_independent() {
        let mut map = HashMap::new();
        let (a0, fam_a) = register_family(&mut map, NOW);
        let (b0, fam_b) = register_family(&mut map, NOW);
        let (a1, _) = rotate(&mut map, &refresh_claims(&a0, &fam_a), NOW).unwrap();
        let _ = rotate(&mut map, &refresh_claims(&a1, &fam_a), NOW).unwrap();
        // Reuse a two-steps-old A token → revokes family A only.
        assert!(rotate(&mut map, &refresh_claims(&a0, &fam_a), NOW).is_none());
        assert!(rotate(&mut map, &refresh_claims(&b0, &fam_b), NOW).is_some());
    }
}

#[cfg(test)]
mod verify_token_tests {
    use super::verify_token;

    #[test]
    fn matching_key_verifies() {
        assert!(verify_token("the-api-key", "the-api-key"));
    }

    #[test]
    fn same_length_non_matching_key_does_not_verify() {
        assert!(!verify_token("the-api-kex", "the-api-key"));
    }
}
