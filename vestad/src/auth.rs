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

/// Accepts either the API key or a valid `X-Agent-Token` belonging to any agent on this
/// host. Gateway-scoped routes (`/version`, `/gateway/...`) have no agent name in the
/// path to scope a token to: the token proves the caller is one of this host's agents,
/// the right tier for host-global reads and the self-update action.
pub async fn auth_middleware_api_or_any_agent_token(
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

    if let Some(provided) = headers.get("x-agent-token").and_then(|v| v.to_str().ok()) {
        if any_agent_token_matches(provided, &state.env_config.agents_dir) {
            return next.run(request).await;
        }
    }
    let path = request.uri().path().to_string();
    tracing::warn!(path = %path, "client auth failed (neither api-key nor any agent-token accepted)");
    unauthorized()
}

/// True when the provided token matches the `AGENT_TOKEN` of any agent env file on this host.
fn any_agent_token_matches(provided: &str, agents_dir: &std::path::Path) -> bool {
    crate::docker::env_file_names(agents_dir).iter().any(|name| {
        let (_, expected) = crate::docker::read_agent_port_and_token(name, agents_dir);
        expected.is_some_and(|expected| expected == provided)
    })
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

/// Every credential the request presents: the Bearer header and the `?token=` query param.
/// One place enumerates them so each carrier is checked identically.
pub(crate) fn presented_tokens<'req>(
    headers: &'req HeaderMap,
    uri: &'req axum::http::Uri,
) -> impl Iterator<Item = &'req str> {
    let bearer = headers
        .get("authorization")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.strip_prefix("Bearer "));
    let query = uri
        .query()
        .and_then(|query| query.split('&').find_map(|pair| pair.strip_prefix("token=")));
    bearer.into_iter().chain(query)
}

pub(crate) fn has_valid_api_auth(
    headers: &HeaderMap,
    uri: &axum::http::Uri,
    api_key: &str,
) -> bool {
    presented_tokens(headers, uri).any(|token| verify_token(token, api_key))
}

/// The agent proxy's authorization decision, in one place. A public service is open; the
/// api key or an access token opens anything; otherwise the request needs a live service
/// key for exactly this agent and service. A key is never accepted on the raw-agent-port
/// fallback (`service` is `None`), which is the only path carrying the injected agent
/// token to the agent's own API. Pure and total, so the whole table is unit-testable.
fn authorizes(
    presented: &[&str],
    api_key: &str,
    agent: &str,
    service_name: &str,
    service: Option<&crate::settings::ServiceEntry>,
    keys: &crate::service_keys::ServiceKeyStore,
    now: u64,
) -> bool {
    if service.is_some_and(|entry| entry.public) {
        return true;
    }
    if presented.iter().any(|&token| verify_token(token, api_key)) {
        return true;
    }
    if service.is_none() {
        return false;
    }
    presented
        .iter()
        .any(|&token| keys.accepts(agent, service_name, token, now))
}

/// Read the key store and the clock, then apply `authorizes`.
pub(crate) async fn proxy_authorized(
    state: &SharedState,
    headers: &HeaderMap,
    uri: &axum::http::Uri,
    agent: &str,
    service_name: &str,
    service: Option<&crate::settings::ServiceEntry>,
) -> bool {
    let presented: Vec<&str> = presented_tokens(headers, uri).collect();
    let now = crate::time_utils::now_epoch_secs();
    let keys = state.service_keys.read().await;
    authorizes(
        &presented,
        &state.api_key,
        agent,
        service_name,
        service,
        &keys,
        now,
    )
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
    hex::encode(rand::random::<[u8; 16]>())
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
/// proved a valid access token (or `api_key`). Used by the hosted (vesta.run) native
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
mod agent_name_extraction {
    use super::extract_agent_name;

    #[test]
    fn agent_paths_self_scope_and_daemon_paths_do_not() {
        assert_eq!(
            extract_agent_name("/agents/alpha/account-token").as_deref(),
            Some("alpha")
        );
        // Daemon-level Vesta Cloud pairing paths carry no agent name; they ride
        // the any-agent-token tier instead of the self-scoped one.
        assert_eq!(extract_agent_name("/vesta-cloud/pair"), None);
        assert_eq!(extract_agent_name("/health"), None);
        assert_eq!(extract_agent_name("/agents"), None);
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

#[cfg(test)]
mod any_agent_token_tests {
    use super::any_agent_token_matches;

    #[test]
    fn matches_the_token_of_any_agent_env_file() {
        let tmp = tempfile::tempdir().expect("tempdir");
        std::fs::write(
            tmp.path().join("alpha.env"),
            "WS_PORT=4001\nAGENT_TOKEN=tok-alpha\n",
        )
        .expect("write alpha env");
        std::fs::write(
            tmp.path().join("beta.env"),
            "export WS_PORT=4002\nexport AGENT_TOKEN=tok-beta\n",
        )
        .expect("write beta env");
        assert!(any_agent_token_matches("tok-alpha", tmp.path()));
        assert!(any_agent_token_matches("tok-beta", tmp.path()));
    }

    #[test]
    fn rejects_an_unknown_token() {
        let tmp = tempfile::tempdir().expect("tempdir");
        std::fs::write(
            tmp.path().join("alpha.env"),
            "WS_PORT=4001\nAGENT_TOKEN=tok-alpha\n",
        )
        .expect("write alpha env");
        assert!(!any_agent_token_matches("tok-other", tmp.path()));
    }

    #[test]
    fn rejects_when_no_agents_exist() {
        let tmp = tempfile::tempdir().expect("tempdir");
        assert!(!any_agent_token_matches("tok-alpha", tmp.path()));
    }
}

#[cfg(test)]
mod presented_tokens_tests {
    use super::presented_tokens;
    use axum::http::{HeaderMap, HeaderValue, Uri};

    fn bearer(token: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        let value = HeaderValue::from_str(&format!("Bearer {token}")).expect("ascii header");
        headers.insert("authorization", value);
        headers
    }

    #[test]
    fn enumerates_the_bearer_header_and_the_token_query_param() {
        let uri = Uri::from_static("/agents/alpha/tasks/tasks?token=from-query");
        let headers = bearer("from-header");
        let found: Vec<&str> = presented_tokens(&headers, &uri).collect();
        assert_eq!(found, vec!["from-header", "from-query"]);
    }

    #[test]
    fn yields_nothing_when_no_credential_is_presented() {
        let uri = Uri::from_static("/agents/alpha/tasks/tasks");
        assert_eq!(presented_tokens(&HeaderMap::new(), &uri).count(), 0);
    }
}

/// One row per security claim `authorizes` makes. Each `assert` is a claim that would be an
/// escalation if it flipped, so the rows are deliberately not collapsed into a loop.
#[cfg(test)]
mod authorization_table {
    use super::{authorizes, presented_tokens};
    use crate::jwt;
    use crate::service_keys::ServiceKeyStore;
    use crate::settings::ServiceEntry;
    use axum::http::{HeaderMap, HeaderValue, Uri};

    const API_KEY: &str = "the-api-key";
    const NOW: u64 = 1_800_000_000;
    const AGENT: &str = "alpha";
    const SERVICE: &str = "dashboard";
    const PRIVATE: ServiceEntry = ServiceEntry {
        port: 9000,
        public: false,
    };
    const PUBLIC: ServiceEntry = ServiceEntry {
        port: 9001,
        public: true,
    };

    /// A store holding one live key for `(alpha, dashboard)`, plus that key's secret.
    fn store_with_live_key() -> (ServiceKeyStore, String) {
        let mut store = ServiceKeyStore::default();
        let (_, secret) = store.mint(AGENT, SERVICE, None, Some(NOW + 600), NOW);
        (store, secret)
    }

    /// The decision for a request to the private `(alpha, dashboard)` service.
    fn opens_private(presented: &[&str], keys: &ServiceKeyStore) -> bool {
        authorizes(presented, API_KEY, AGENT, SERVICE, Some(&PRIVATE), keys, NOW)
    }

    #[test]
    fn a_public_service_opens_with_no_credential_at_all() {
        let keys = ServiceKeyStore::default();
        assert!(authorizes(
            &[],
            API_KEY,
            AGENT,
            SERVICE,
            Some(&PUBLIC),
            &keys,
            NOW
        ));
    }

    #[test]
    fn the_raw_api_key_opens_a_private_registered_service() {
        let keys = ServiceKeyStore::default();
        assert!(opens_private(&[API_KEY], &keys));
    }

    #[test]
    fn an_access_jwt_opens_a_private_registered_service() {
        let keys = ServiceKeyStore::default();
        let access = jwt::create_token(API_KEY, "access", jwt::ACCESS_TOKEN_TTL);
        assert!(opens_private(&[access.as_str()], &keys));
    }

    #[test]
    fn a_live_key_opens_its_own_service_through_the_bearer_header() {
        let (keys, secret) = store_with_live_key();
        let mut headers = HeaderMap::new();
        let value = HeaderValue::from_str(&format!("Bearer {secret}")).expect("ascii header");
        headers.insert("authorization", value);
        let uri = Uri::from_static("/agents/alpha/dashboard/");
        let presented: Vec<&str> = presented_tokens(&headers, &uri).collect();
        assert!(opens_private(&presented, &keys));
    }

    #[test]
    fn a_live_key_opens_its_own_service_through_the_token_query_param() {
        let (keys, secret) = store_with_live_key();
        let uri: Uri = format!("/agents/alpha/dashboard/?token={secret}")
            .parse()
            .expect("valid uri");
        let headers = HeaderMap::new();
        let presented: Vec<&str> = presented_tokens(&headers, &uri).collect();
        assert!(opens_private(&presented, &keys));
    }

    #[test]
    fn a_key_for_another_agent_is_refused() {
        let (keys, secret) = store_with_live_key();
        assert!(!authorizes(
            &[secret.as_str()],
            API_KEY,
            "beta",
            SERVICE,
            Some(&PRIVATE),
            &keys,
            NOW
        ));
    }

    #[test]
    fn a_key_for_another_service_on_the_same_agent_is_refused() {
        let (keys, secret) = store_with_live_key();
        assert!(!authorizes(
            &[secret.as_str()],
            API_KEY,
            AGENT,
            "voice",
            Some(&PRIVATE),
            &keys,
            NOW
        ));
    }

    /// No registered service matched, so this is the raw-agent-port fallback, the one path
    /// that injects `X-Agent-Token` for the agent's own privileged API. A key must not reach
    /// it, while the api key still must.
    #[test]
    fn a_key_is_refused_when_no_registered_service_matched() {
        let (keys, secret) = store_with_live_key();
        assert!(!authorizes(
            &[secret.as_str()],
            API_KEY,
            AGENT,
            SERVICE,
            None,
            &keys,
            NOW
        ));
        assert!(authorizes(&[API_KEY], API_KEY, AGENT, SERVICE, None, &keys, NOW));
    }

    #[test]
    fn an_expired_key_is_refused() {
        let mut keys = ServiceKeyStore::default();
        let (_, secret) = keys.mint(AGENT, SERVICE, None, Some(NOW - 1), NOW);
        assert!(!opens_private(&[secret.as_str()], &keys));
    }

    #[test]
    fn a_bare_request_is_refused_on_a_private_registered_service() {
        let (keys, _) = store_with_live_key();
        assert!(!opens_private(&[], &keys));
        assert!(!opens_private(&["not-a-credential"], &keys));
    }
}

#[cfg(test)]
mod api_auth_tests {
    use super::has_valid_api_auth;
    use crate::service_keys::ServiceKeyStore;
    use axum::http::{HeaderMap, HeaderValue, Uri};

    const API_KEY: &str = "the-api-key";
    const NOW: u64 = 1_800_000_000;
    const NO_QUERY: &str = "/agents/alpha/dashboard/";

    fn bearer(token: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        let value = HeaderValue::from_str(&format!("Bearer {token}")).expect("ascii header");
        headers.insert("authorization", value);
        headers
    }

    fn query_uri(token: &str) -> Uri {
        format!("{NO_QUERY}?token={token}")
            .parse()
            .expect("valid uri")
    }

    #[test]
    fn the_api_key_opens_a_route_through_either_carrier() {
        assert!(has_valid_api_auth(
            &bearer(API_KEY),
            &Uri::from_static(NO_QUERY),
            API_KEY
        ));
        assert!(has_valid_api_auth(
            &HeaderMap::new(),
            &query_uri(API_KEY),
            API_KEY
        ));
    }

    #[test]
    fn a_wrong_or_absent_token_is_refused_in_either_carrier() {
        let plain = Uri::from_static(NO_QUERY);
        assert!(!has_valid_api_auth(&bearer("not-the-key"), &plain, API_KEY));
        assert!(!has_valid_api_auth(
            &HeaderMap::new(),
            &query_uri("not-the-key"),
            API_KEY
        ));
        assert!(!has_valid_api_auth(&HeaderMap::new(), &plain, API_KEY));
    }

    /// Every api-key middleware (gateway admin, agent admin, `/sync`, the mint route
    /// itself) runs on `has_valid_api_auth`. A service key opening none of them is what
    /// keeps a key scoped to its one service instead of becoming a gateway credential,
    /// so it must be refused in both carriers the proxy also reads it from.
    #[test]
    fn a_service_key_is_not_an_api_credential() {
        let mut store = ServiceKeyStore::default();
        let (_, secret) = store.mint("alpha", "dashboard", None, Some(NOW + 600), NOW);
        assert!(!has_valid_api_auth(
            &bearer(&secret),
            &Uri::from_static(NO_QUERY),
            API_KEY
        ));
        assert!(!has_valid_api_auth(
            &HeaderMap::new(),
            &query_uri(&secret),
            API_KEY
        ));
    }
}
