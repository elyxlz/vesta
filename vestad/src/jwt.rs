use ring::hmac;
use serde::{Deserialize, Serialize};

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
    let mut out = String::new();
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut i = 0;
    while i < data.len() {
        let b0 = data[i] as usize;
        let b1 = if i + 1 < data.len() { data[i + 1] as usize } else { 0 };
        let b2 = if i + 2 < data.len() { data[i + 2] as usize } else { 0 };
        out.push(CHARS[b0 >> 2] as char);
        out.push(CHARS[((b0 & 3) << 4) | (b1 >> 4)] as char);
        if i + 1 < data.len() {
            out.push(CHARS[((b1 & 0xf) << 2) | (b2 >> 6)] as char);
        }
        if i + 2 < data.len() {
            out.push(CHARS[b2 & 0x3f] as char);
        }
        i += 3;
    }
    out
}

fn b64url_decode(s: &str) -> Result<Vec<u8>, JwtError> {
    let mut table = [255u8; 128];
    for (i, &c) in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_".iter().enumerate() {
        table[c as usize] = i as u8;
    }

    let bytes: Vec<u8> = s.bytes().map(|b| {
        if (b as usize) < 128 { table[b as usize] } else { 255 }
    }).collect();

    if bytes.contains(&255) {
        return Err(JwtError::DecodeFailed);
    }

    let mut out = Vec::with_capacity(bytes.len() * 3 / 4);
    let chunks = bytes.chunks(4);
    for chunk in chunks {
        let len = chunk.len();
        if len >= 2 {
            out.push((chunk[0] << 2) | (chunk[1] >> 4));
        }
        if len >= 3 {
            out.push((chunk[1] << 4) | (chunk[2] >> 2));
        }
        if len >= 4 {
            out.push((chunk[2] << 6) | chunk[3]);
        }
    }
    Ok(out)
}

const HEADER_B64: &str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"; // {"alg":"HS256","typ":"JWT"}

fn now_epoch_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub fn create_token(api_key: &str, typ: &str, ttl_secs: u64) -> String {
    let now = now_epoch_secs();

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

    if claims.exp < now_epoch_secs() {
        return Err(JwtError::Expired);
    }

    if claims.typ != expected_typ {
        return Err(JwtError::WrongType);
    }

    Ok(claims)
}
