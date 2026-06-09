use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};

pub const ACCESS_TOKEN_TTL: u64 = 3600; // 1 hour
pub const REFRESH_TOKEN_TTL: u64 = 7 * 86400; // 7 days

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
}

pub fn create_token(api_key: &str, typ: &str, ttl_secs: u64) -> String {
    let now = crate::time_utils::now_epoch_secs();
    let claims = Claims {
        sub: "vesta-app".into(),
        typ: typ.into(),
        iat: now,
        exp: now + ttl_secs,
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(api_key.as_bytes()),
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
    };
    encode(
        &Header::new(Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(api_key.as_bytes()),
    )
    .expect("HS256 encoding of a serializable struct is infallible")
}

pub fn validate_token(api_key: &str, token: &str, expected_typ: &str) -> Result<Claims, jsonwebtoken::errors::Error> {
    let mut validation = Validation::new(Algorithm::HS256);
    // Tokens carry no audience claim; only `exp` (validated by default) is required.
    validation.validate_aud = false;
    let claims = decode::<Claims>(token, &DecodingKey::from_secret(api_key.as_bytes()), &validation)?.claims;
    if claims.typ != expected_typ {
        return Err(jsonwebtoken::errors::ErrorKind::InvalidToken.into());
    }
    Ok(claims)
}

#[cfg(test)]
mod tests {
    use super::*;

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
