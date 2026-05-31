use jsonwebtoken::{decode, encode, Algorithm, DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};

pub const ACCESS_TOKEN_TTL: u64 = 3600; // 1 hour
pub const REFRESH_TOKEN_TTL: u64 = 7 * 86400; // 7 days

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
}
