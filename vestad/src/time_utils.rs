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
    let dt = time::OffsetDateTime::from_unix_timestamp(epoch_secs as i64)
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

fn local_tm(epoch_secs: u64) -> libc::tm {
    let epoch = epoch_secs as libc::time_t;
    // SAFETY: libc::tm is a plain-integer C struct for which an all-zero bit pattern is valid.
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    // SAFETY: &epoch and &mut tm are valid, non-overlapping, properly aligned pointers for the
    // duration of the call.
    unsafe { libc::localtime_r(&epoch, &mut tm) };
    tm
}

/// The host-local hour of day (0-23) right now.
pub fn local_hour() -> u8 {
    local_tm(now_epoch_secs()).tm_hour as u8
}

/// Host-local calendar date (YYYYMMDD) for an epoch. Keying the once-per-day backup dedup to this
/// same wall clock as the firing window avoids the UTC-vs-local day-boundary mismatch that could
/// otherwise double or skip a daily near midnight.
pub fn local_date_of_epoch(epoch_secs: u64) -> String {
    let tm = local_tm(epoch_secs);
    format!("{:04}{:02}{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday)
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
