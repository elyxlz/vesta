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

/// The compact `YYYYMMDD-HHMMSS` UTC timestamp (the backup `created_at` format) for the current moment.
pub fn now_timestamp() -> String {
    now_timestamp_from_epoch(now_epoch_secs())
}

/// The compact `YYYYMMDD-HHMMSS` UTC timestamp for an epoch.
pub fn now_timestamp_from_epoch(epoch_secs: u64) -> String {
    let epoch = i64::try_from(epoch_secs).expect("epoch seconds fit in i64");
    let dt = time::OffsetDateTime::from_unix_timestamp(epoch)
        .expect("epoch seconds within valid range");
    let fmt = time::macros::format_description!("[year][month][day]-[hour][minute][second]");
    dt.format(&fmt).expect("timestamp format never fails")
}

/// Parse a compact `YYYYMMDD-HHMMSS` UTC timestamp back to epoch seconds.
/// Inverse of `now_timestamp_from_epoch`; returns None on malformed input.
pub fn parse_compact_utc_epoch(created_at: &str) -> Option<u64> {
    let fmt = time::macros::format_description!("[year][month][day]-[hour][minute][second]");
    let dt = time::PrimitiveDateTime::parse(created_at.trim(), &fmt).ok()?;
    u64::try_from(dt.assume_utc().unix_timestamp()).ok()
}

/// The RFC3339 timestamp for an epoch, fallible so no unwrap rides the notification send path.
pub fn epoch_to_rfc3339(epoch_secs: u64) -> Result<String, String> {
    let epoch = i64::try_from(epoch_secs).map_err(|e| format!("epoch out of range: {e}"))?;
    time::OffsetDateTime::from_unix_timestamp(epoch)
        .map_err(|e| format!("epoch out of range: {e}"))?
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|e| format!("format timestamp: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_compact_utc_epoch_roundtrips() {
        let epoch = 1_780_000_000u64;
        let ts = now_timestamp_from_epoch(epoch);
        assert_eq!(parse_compact_utc_epoch(&ts), Some(epoch));
    }

    #[test]
    fn parse_compact_utc_epoch_rejects_malformed() {
        assert_eq!(parse_compact_utc_epoch("not-a-timestamp"), None);
        assert_eq!(parse_compact_utc_epoch(""), None);
    }
}
