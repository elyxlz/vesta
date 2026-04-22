/// Seconds since the Unix epoch. Falls back to 0 if the system clock is before
/// 1970 (effectively never, but we don't panic on it).
pub fn now_epoch_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Milliseconds since the Unix epoch. Same fallback as `now_epoch_secs`.
pub fn now_epoch_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}
