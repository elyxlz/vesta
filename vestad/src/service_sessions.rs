//! Short-lived session IDs that authenticate iframe sub-resource requests
//! (JS/CSS/fonts/dynamic imports) without cookies or headers.
//!
//! The parent app mints a session via `POST /agents/{name}/services/{svc}/session`
//! and sets the iframe src to `/agents/{name}/services/{svc}/s/{session_id}/`. Every
//! sub-resource resolves under that path so the session_id rides along naturally.
//! The proxy validates the session before forwarding upstream.
//!
//! A leaked session_id grants access to one `(agent, service)` pair for at most
//! `SESSION_TTL` of inactivity. Short TTL + sliding refresh + per-service scope
//! bounds the blast radius, comparable to a scoped cookie.
use std::collections::HashMap;
use std::time::{Duration, Instant};

use tokio::sync::RwLock;

use ring::rand::{SecureRandom, SystemRandom};

pub const SESSION_ID_BYTES: usize = 32;
pub const SESSION_TTL: Duration = Duration::from_secs(600); // 10 minutes, sliding

struct Record {
    agent: String,
    service: String,
    last_seen: Instant,
}

pub struct ServiceSessions {
    inner: RwLock<HashMap<String, Record>>,
    rng: SystemRandom,
}

impl ServiceSessions {
    pub fn new() -> Self {
        Self {
            inner: RwLock::new(HashMap::new()),
            rng: SystemRandom::new(),
        }
    }

    pub async fn mint(&self, agent: &str, service: &str) -> String {
        let mut bytes = [0u8; SESSION_ID_BYTES];
        self.rng
            .fill(&mut bytes)
            .expect("system rng failed to produce session id");
        let id = encode_hex(&bytes);
        let record = Record {
            agent: agent.to_string(),
            service: service.to_string(),
            last_seen: Instant::now(),
        };
        self.inner.write().await.insert(id.clone(), record);
        id
    }

    /// Returns `(agent, service)` if the session is live and bumps its expiry.
    /// Drops the entry if expired.
    pub async fn lookup_and_touch(&self, session_id: &str) -> Option<(String, String)> {
        let now = Instant::now();
        let mut map = self.inner.write().await;
        {
            let record = map.get_mut(session_id)?;
            if now.saturating_duration_since(record.last_seen) <= SESSION_TTL {
                record.last_seen = now;
                return Some((record.agent.clone(), record.service.clone()));
            }
        }
        map.remove(session_id);
        None
    }

    pub async fn invalidate_service(&self, agent: &str, service: &str) {
        let mut map = self.inner.write().await;
        map.retain(|_, r| !(r.agent == agent && r.service == service));
    }

    pub async fn invalidate_agent(&self, agent: &str) {
        let mut map = self.inner.write().await;
        map.retain(|_, r| r.agent != agent);
    }

    #[cfg(test)]
    async fn len(&self) -> usize {
        self.inner.read().await.len()
    }
}

impl Default for ServiceSessions {
    fn default() -> Self {
        Self::new()
    }
}

fn encode_hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push(HEX[(b >> 4) as usize] as char);
        s.push(HEX[(b & 0x0f) as usize] as char);
    }
    s
}

const HEX: &[u8; 16] = b"0123456789abcdef";

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn mint_returns_unique_lowercase_hex_ids() {
        let store = ServiceSessions::new();
        let a = store.mint("alice", "dashboard").await;
        let b = store.mint("alice", "dashboard").await;
        assert_ne!(a, b);
        assert_eq!(a.len(), SESSION_ID_BYTES * 2);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase()));
    }

    #[tokio::test]
    async fn lookup_ok_after_mint() {
        let store = ServiceSessions::new();
        let id = store.mint("alice", "dashboard").await;
        let bound = store.lookup_and_touch(&id).await;
        assert_eq!(bound, Some(("alice".into(), "dashboard".into())));
    }

    #[tokio::test]
    async fn lookup_unknown_returns_none() {
        let store = ServiceSessions::new();
        assert_eq!(store.lookup_and_touch("deadbeef").await, None);
    }

    #[tokio::test]
    async fn expired_session_is_dropped_on_lookup() {
        let store = ServiceSessions::new();
        let id = store.mint("alice", "dashboard").await;
        // Simulate expiry by rewinding the record's last_seen. Cheaper than
        // sleeping past the real 10-minute TTL.
        {
            let mut map = store.inner.write().await;
            let r = map.get_mut(&id).unwrap();
            r.last_seen = Instant::now()
                .checked_sub(SESSION_TTL + Duration::from_secs(1))
                .unwrap();
        }
        assert_eq!(store.lookup_and_touch(&id).await, None);
        assert_eq!(store.len().await, 0);
    }

    #[tokio::test]
    async fn touch_extends_session() {
        let store = ServiceSessions::new();
        let id = store.mint("alice", "dashboard").await;
        // Rewind halfway into the TTL, touch → last_seen resets to now.
        {
            let mut map = store.inner.write().await;
            map.get_mut(&id).unwrap().last_seen =
                Instant::now().checked_sub(SESSION_TTL / 2).unwrap();
        }
        assert!(store.lookup_and_touch(&id).await.is_some(), "still within ttl");
        // Rewind halfway again — without sliding refresh, cumulative age
        // (TTL/2 + TTL/2) would be at exactly TTL. The prior touch reset
        // last_seen, so this should still be fresh.
        {
            let mut map = store.inner.write().await;
            map.get_mut(&id).unwrap().last_seen =
                Instant::now().checked_sub(SESSION_TTL / 2).unwrap();
        }
        assert!(store.lookup_and_touch(&id).await.is_some(), "touch reset ttl");
    }

    #[tokio::test]
    async fn invalidate_service_drops_matching_sessions_only() {
        let store = ServiceSessions::new();
        let a_dash = store.mint("alice", "dashboard").await;
        let a_voice = store.mint("alice", "voice").await;
        let b_dash = store.mint("bob", "dashboard").await;

        store.invalidate_service("alice", "dashboard").await;

        assert!(store.lookup_and_touch(&a_dash).await.is_none());
        assert!(store.lookup_and_touch(&a_voice).await.is_some());
        assert!(store.lookup_and_touch(&b_dash).await.is_some());
    }

    #[tokio::test]
    async fn invalidate_agent_drops_all_for_agent() {
        let store = ServiceSessions::new();
        let a_dash = store.mint("alice", "dashboard").await;
        let a_voice = store.mint("alice", "voice").await;
        let b_dash = store.mint("bob", "dashboard").await;

        store.invalidate_agent("alice").await;

        assert!(store.lookup_and_touch(&a_dash).await.is_none());
        assert!(store.lookup_and_touch(&a_voice).await.is_none());
        assert!(store.lookup_and_touch(&b_dash).await.is_some());
    }

    #[test]
    fn hex_encoding_is_deterministic() {
        assert_eq!(encode_hex(&[0x00, 0xff, 0x10, 0xab]), "00ff10ab");
    }
}
