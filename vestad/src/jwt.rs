use base64::Engine;
use ring::hmac;
use serde::{Deserialize, Serialize};

const B64: base64::engine::GeneralPurpose = base64::engine::general_purpose::URL_SAFE_NO_PAD;

pub const ACCESS_TOKEN_TTL: u64 = 3600; // 1 hour
pub const REFRESH_TOKEN_TTL: u64 = 7 * 86400; // 7 days

#[derive(Debug)]
pub enum JwtError {
    InvalidFormat,
    InvalidSignature,
    Expired,
    WrongType,
    DecodeFailed,
}

impl std::fmt::Display for JwtError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidFormat => write!(f, "invalid token format"),
            Self::InvalidSignature => write!(f, "invalid signature"),
            Self::Expired => write!(f, "token expired"),
            Self::WrongType => write!(f, "wrong token type"),
            Self::DecodeFailed => write!(f, "failed to decode token"),
        }
    }
}

#[derive(Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub typ: String,
    pub iat: u64,
    pub exp: u64,
}

fn b64url_encode(data: &[u8]) -> String {
    B64.encode(data)
}

fn b64url_decode(s: &str) -> Result<Vec<u8>, JwtError> {
    B64.decode(s).map_err(|_| JwtError::DecodeFailed)
}

const HEADER_B64: &str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"; // {"alg":"HS256","typ":"JWT"}

pub fn create_token(api_key: &str, typ: &str, ttl_secs: u64) -> String {
    let now = crate::time_utils::now_epoch_secs();

    let claims = Claims {
        sub: "vesta-app".into(),
        typ: typ.into(),
        iat: now,
        exp: now + ttl_secs,
    };

    let payload_json = serde_json::to_string(&claims).unwrap();
    let payload_b64 = b64url_encode(payload_json.as_bytes());
    let message = format!("{}.{}", HEADER_B64, payload_b64);

    let key = hmac::Key::new(hmac::HMAC_SHA256, api_key.as_bytes());
    let sig = hmac::sign(&key, message.as_bytes());
    let sig_b64 = b64url_encode(sig.as_ref());

    format!("{}.{}", message, sig_b64)
}

pub fn validate_token(api_key: &str, token: &str, expected_typ: &str) -> Result<Claims, JwtError> {
    let parts: Vec<&str> = token.splitn(3, '.').collect();
    if parts.len() != 3 {
        return Err(JwtError::InvalidFormat);
    }

    let message = format!("{}.{}", parts[0], parts[1]);
    let sig_bytes = b64url_decode(parts[2])?;

    let key = hmac::Key::new(hmac::HMAC_SHA256, api_key.as_bytes());
    hmac::verify(&key, message.as_bytes(), &sig_bytes)
        .map_err(|_| JwtError::InvalidSignature)?;

    let payload_bytes = b64url_decode(parts[1])?;
    let claims: Claims = serde_json::from_slice(&payload_bytes)
        .map_err(|_| JwtError::DecodeFailed)?;

    if claims.exp < crate::time_utils::now_epoch_secs() {
        return Err(JwtError::Expired);
    }

    if claims.typ != expected_typ {
        return Err(JwtError::WrongType);
    }

    Ok(claims)
}
