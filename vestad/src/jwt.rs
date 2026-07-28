use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use ring::hkdf;
use serde::{Deserialize, Serialize};

pub const ACCESS_TOKEN_TTL: u64 = 3600; // 1 hour
/// Idle window, not an absolute lifetime: every successful rotation slides the
/// family expiry forward by this much, so only a client idle this long re-auths.
pub const REFRESH_TOKEN_TTL: u64 = 30 * 86400; // 30 days

// --- Per-purpose key derivation (HKDF-SHA256) ---------------------------------
//
// Every token is HS256-signed, but NOT with the raw `api_key`: a distinct subkey per
// purpose means a token minted for one role cannot verify for another, cryptographically
// (the `typ` claim stays as defense-in-depth). CROSS-REPO CONTRACT: the vesta-cloud
// control plane derives the SAME subkeys (functions/lib/tokens.ts), so these constants
// and the derivation (salt, label = PREFIX || typ, 32-byte output) MUST stay
// byte-identical on both sides. The known-answer test below pins the vector.
const HKDF_SALT: &[u8] = b"vesta-auth-hkdf-v1";
const KEY_LABEL_PREFIX: &[u8] = b"vesta/auth/";

/// `KeyType` for `hkdf::Prk::expand` — fixes the derived-key length at 32 bytes.
struct OkmLen;
impl hkdf::KeyType for OkmLen {
    fn len(&self) -> usize {
        32
    }
}

/// Derive the HS256 signing/verifying key for `typ` from the per-VM `api_key`.
/// `info = KEY_LABEL_PREFIX || typ`, so each role ("access", "refresh",
/// "server-identity") gets its own subkey — the label IS the role.
fn signing_key(api_key: &str, typ: &str) -> [u8; 32] {
    let prk = hkdf::Salt::new(hkdf::HKDF_SHA256, HKDF_SALT).extract(api_key.as_bytes());
    let info = [KEY_LABEL_PREFIX, typ.as_bytes()];
    let okm = prk
        .expand(&info, OkmLen)
        .expect("hkdf expand to 32 bytes is infallible");
    let mut out = [0u8; 32];
    okm.fill(&mut out)
        .expect("hkdf fill of matching length is infallible");
    out
}

/// `typ` of a server-identity token — the VM proving its OWN identity to the
/// vesta-cloud control plane (issue #20), distinct from the `"access"` token the
/// app consumes so neither can be replayed in the other's role.
pub const SERVER_IDENTITY_TYP: &str = "server-identity";
/// Server-identity token TTL — short; minted on demand, carried once.
pub const SERVER_IDENTITY_TTL: u64 = 600; // 10 minutes

#[derive(Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub typ: String,
    pub iat: u64,
    pub exp: u64,
    /// Refresh-token id (rotation): present only on `typ:"refresh"` tokens, so
    /// each one is individually trackable + revocable. Absent on access/identity.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub jti: Option<String>,
    /// Refresh-token family id: all rotations of one login share it, so reuse of a
    /// spent token revokes the whole chain (RFC 9700 §4.14).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fam: Option<String>,
}

pub fn create_token(api_key: &str, typ: &str, ttl_secs: u64) -> String {
    let now = crate::time_utils::now_epoch_secs();
    let claims = Claims {
        sub: "vesta-app".into(),
        typ: typ.into(),
        iat: now,
        exp: now + ttl_secs,
        jti: None,
        fam: None,
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(&signing_key(api_key, typ)),
    )
    .expect("HS256 encoding of a serializable struct is infallible")
}

/// Mint a ROTATING refresh token: `{ typ:"refresh", jti, fam }` signed with the
/// `api_key`. The `jti`/`fam` let the issuer (this vestad) rotate it on use and
/// revoke a whole family on reuse, satisfying RFC 9700 §2.2.2 for public clients.
pub fn create_refresh_token(api_key: &str, jti: &str, fam: &str) -> String {
    let now = crate::time_utils::now_epoch_secs();
    let claims = Claims {
        sub: "vesta-app".into(),
        typ: "refresh".into(),
        iat: now,
        exp: now + REFRESH_TOKEN_TTL,
        jti: Some(jti.into()),
        fam: Some(fam.into()),
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(&signing_key(api_key, "refresh")),
    )
    .expect("HS256 encoding of a serializable struct is infallible")
}

/// Mint a server-identity token: `{ sub: <server_id>, typ: "server-identity" }`
/// signed with this VM's `api_key`.
///
/// This is a PURE LOCAL operation — vestad never calls the control plane. The
/// on-box agent carries this token to the control plane's `/api/account/*`,
/// which reads `sub` to find the server row and verifies the signature with THAT
/// row's `api_key`, authenticating the caller as exactly this server.
pub fn create_server_identity_token(api_key: &str, server_id: &str) -> String {
    let now = crate::time_utils::now_epoch_secs();
    let claims = Claims {
        sub: server_id.into(),
        typ: SERVER_IDENTITY_TYP.into(),
        iat: now,
        exp: now + SERVER_IDENTITY_TTL,
        jti: None,
        fam: None,
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(&signing_key(api_key, SERVER_IDENTITY_TYP)),
    )
    .expect("HS256 encoding of a serializable struct is infallible")
}

pub fn validate_token(
    api_key: &str,
    token: &str,
    expected_typ: &str,
) -> Result<Claims, jsonwebtoken::errors::Error> {
    let mut validation = Validation::new(Algorithm::HS256);
    // Tokens carry no audience claim; only `exp` (validated by default) is required.
    validation.validate_aud = false;
    // Verify under the subkey derived for the EXPECTED role: a token minted for
    // another role won't even verify here (defense beyond the `typ` check below).
    let key = signing_key(api_key, expected_typ);
    let claims = decode::<Claims>(token, &DecodingKey::from_secret(&key), &validation)?.claims;
    if claims.typ != expected_typ {
        return Err(jsonwebtoken::errors::ErrorKind::InvalidToken.into());
    }
    Ok(claims)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }

    // CROSS-REPO CONTRACT: these vectors pin HKDF(api_key, "vesta/auth/"||typ).
    // The twin test in vesta-cloud (functions/lib/__tests__/tokens.test.ts) pins
    // the SAME values; if either repo's derivation drifts, its test fails.
    const VECTOR_API_KEY: &str = "vesta-auth-hkdf-test-vector";

    #[test]
    fn derived_keys_match_cross_repo_vector() {
        assert_eq!(
            hex(&signing_key(VECTOR_API_KEY, "access")),
            "053b2ecb9c39a57934146727d3572f4485505b52c9c632b6fa124612eebee828"
        );
        assert_eq!(
            hex(&signing_key(VECTOR_API_KEY, "refresh")),
            "2cc6a960bc8986cc6e2bca9d2964ecc453820fe7aaefcc10bb83cf5daf74efd7"
        );
        assert_eq!(
            hex(&signing_key(VECTOR_API_KEY, "server-identity")),
            "852ca4fc9d91a8537c802bcc4687a27b3dada004cf6fde2816b8460c2caf547b"
        );
    }

    #[test]
    fn each_role_derives_a_distinct_key() {
        let a = signing_key("k", "access");
        let r = signing_key("k", "refresh");
        let i = signing_key("k", "server-identity");
        assert_ne!(a, r);
        assert_ne!(a, i);
        assert_ne!(r, i);
    }

    #[test]
    fn access_token_cannot_be_replayed_as_another_role() {
        // An access token must not verify as refresh or server-identity: the
        // derived subkey differs, so the SIGNATURE fails (not just the typ check).
        let token = create_token("secret", "access", ACCESS_TOKEN_TTL);
        assert!(validate_token("secret", &token, "refresh").is_err());
        assert!(validate_token("secret", &token, SERVER_IDENTITY_TYP).is_err());
        assert!(validate_token("secret", &token, "access").is_ok());
    }

    #[test]
    fn roundtrip_valid() {
        let token = create_token("secret", "access", ACCESS_TOKEN_TTL);
        let claims = validate_token("secret", &token, "access").expect("valid token");
        assert_eq!(claims.sub, "vesta-app");
        assert_eq!(claims.typ, "access");
    }

    #[test]
    fn wrong_type_rejected() {
        let token = create_token("secret", "refresh", REFRESH_TOKEN_TTL);
        assert!(validate_token("secret", &token, "access").is_err());
    }

    #[test]
    fn wrong_key_rejected() {
        let token = create_token("secret", "access", ACCESS_TOKEN_TTL);
        assert!(validate_token("other-secret", &token, "access").is_err());
    }

    #[test]
    fn server_identity_carries_server_id_and_typ() {
        let token = create_server_identity_token("secret", "srv_abc");
        // Verifies under the signing key, with the server id in `sub`.
        let claims = validate_token("secret", &token, SERVER_IDENTITY_TYP).expect("valid token");
        assert_eq!(claims.sub, "srv_abc");
        assert_eq!(claims.typ, SERVER_IDENTITY_TYP);
        // Cannot be replayed as an `access` token (wrong typ) ...
        assert!(validate_token("secret", &token, "access").is_err());
        // ... nor verified under another VM's key.
        assert!(validate_token("other-secret", &token, SERVER_IDENTITY_TYP).is_err());
    }
}
