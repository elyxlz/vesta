//! Choosing when the maintenance pass (snapshots, plus a pending update) runs so it disturbs
//! the fewest agents.
//!
//! An update restarts every agent container at once (that invariant stays), so a single instant
//! must serve the whole fleet. We aim it at the upcoming 4-5am window that covers the most agents
//! in their own local time: agents sharing a timezone stack, and nearby timezones' windows overlap
//! and stack too. Maintenance always lands within 24h (each zone hits 4-5am daily), after the
//! agents' own dreams (default hour 3), at the least-disruptive moment.

use jiff::{tz::TimeZone, SignedDuration, Timestamp};

const WINDOW_START_HOUR: i8 = 4;
const WINDOW_END_HOUR: i8 = 5;
const SCAN_HORIZON_HOURS: i64 = 24;
const SCAN_STEP_MINUTES: i64 = 15;
/// Upper bound on the per-night open jitter: the effective window keeps at least 30 minutes,
/// so an idle-gated poll and the closing poll both still fit before the fixed 5:00 close. This
/// must stay above `2 * SCAN_STEP_MINUTES`; raising the jitter cap or the poll step without the
/// other can shrink the window below room for both polls.
const WINDOW_JITTER_MINUTES: u64 = 30;

/// The minute past 4:00 the window opens on `date`'s night, hashed (FNV-1a) from the zone-local
/// date: stable across polls and vestad restarts, different each night, so the pass never lands
/// on the same clock minute night after night.
fn jitter_minutes(date: jiff::civil::Date) -> i8 {
    const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
    const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;
    let mut hash = FNV_OFFSET;
    for byte in date.to_string().bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    i8::try_from(hash % WINDOW_JITTER_MINUTES).expect("jitter is below 30")
}

/// Resolve an agent's reported IANA timezone name to a zone, falling back to the vestad host's
/// local zone when the agent reported none (pre-upstream-sync fleet) or the name doesn't parse.
/// Degrading to host-local keeps the update flowing rather than stalling on a missing timezone.
pub fn resolve_zone(name: Option<&str>) -> TimeZone {
    name.and_then(|name| TimeZone::get(name).ok()).unwrap_or_else(TimeZone::system)
}

/// Whether `at` falls inside the `[4:JJ, 5:00)` local window for `zone`, `JJ` being the night's
/// jitter minute. The single-hour window makes the minute check apply exactly at the open hour.
fn in_window(zone: &TimeZone, at: Timestamp) -> bool {
    let zoned = at.to_zoned(zone.clone());
    (WINDOW_START_HOUR..WINDOW_END_HOUR).contains(&zoned.hour()) && zoned.minute() >= jitter_minutes(zoned.date())
}

/// How long to wait from `now` before running maintenance so it lands in the upcoming 4-5am
/// window covering the most agents. Zero means run now: either there are no agents to protect,
/// or now is already the fullest window. Scans the next 24h in 15-minute steps and returns the
/// offset of the earliest step reaching the maximum coverage.
pub fn wait_until_best_window(zones: &[TimeZone], now: Timestamp) -> SignedDuration {
    if zones.is_empty() {
        return SignedDuration::ZERO;
    }
    let steps = (SCAN_HORIZON_HOURS * 60) / SCAN_STEP_MINUTES;
    let mut best_count = 0;
    let mut best_offset_mins = 0;
    for step in 0..=steps {
        let offset_mins = step * SCAN_STEP_MINUTES;
        let at = now + SignedDuration::from_mins(offset_mins);
        let count = zones.iter().filter(|zone| in_window(zone, at)).count();
        // Strictly-greater keeps the earliest instant of the daily maximum (later equal-count
        // steps within the same window never overwrite it), so we apply as soon as coverage peaks.
        if count > best_count {
            best_count = count;
            best_offset_mins = offset_mins;
        }
    }
    SignedDuration::from_mins(best_offset_mins)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ts(s: &str) -> Timestamp {
        s.parse().expect("valid timestamp")
    }

    fn zone(name: &str) -> TimeZone {
        TimeZone::get(name).expect("known zone")
    }

    #[test]
    fn in_window_utc_boundaries_open_at_the_jitter_minute() {
        // fnv1a("2026-01-01") % 30 == 19: this night's window is [4:19, 5:00).
        let utc = zone("UTC");
        assert!(!in_window(&utc, ts("2026-01-01T03:59:00Z")));
        assert!(!in_window(&utc, ts("2026-01-01T04:18:00Z")));
        assert!(in_window(&utc, ts("2026-01-01T04:19:00Z")));
        assert!(in_window(&utc, ts("2026-01-01T04:59:00Z")));
        assert!(!in_window(&utc, ts("2026-01-01T05:00:00Z")));
    }

    #[test]
    fn window_open_minute_changes_across_nights() {
        // fnv1a("2026-01-02") % 30 == 20: the next night opens one minute later, so the pass
        // cannot land on the same clock minute night after night. The close edge stays 5:00.
        let utc = zone("UTC");
        assert!(!in_window(&utc, ts("2026-01-02T04:19:00Z")));
        assert!(in_window(&utc, ts("2026-01-02T04:20:00Z")));
        assert!(in_window(&utc, ts("2026-01-02T04:59:00Z")));
        assert!(!in_window(&utc, ts("2026-01-02T05:00:00Z")));
    }

    #[test]
    fn in_window_respects_offset_zone_in_winter() {
        // New York is UTC-5 in January, so 04:19 EST (the night's open, jitter 19) == 09:19 UTC.
        let ny = zone("America/New_York");
        assert!(in_window(&ny, ts("2026-01-01T09:19:00Z")));
        assert!(!in_window(&ny, ts("2026-01-01T06:19:00Z"))); // 01:19 EST
    }

    #[test]
    fn in_window_respects_dst_shift_in_summer() {
        // New York is UTC-4 in July (EDT): 04:29 EDT (jitter 29) == 08:29 UTC is in-window, while
        // 09:29 UTC == 05:29 EDT is out -- in winter that same wall-clock check sat an hour later in
        // UTC (asserted above), so the zone's DST offset is being applied, not a fixed one.
        let ny = zone("America/New_York");
        assert!(in_window(&ny, ts("2026-07-01T08:29:00Z")));
        assert!(!in_window(&ny, ts("2026-07-01T09:29:00Z")));
    }

    #[test]
    fn wait_until_best_window_picks_the_least_disruptive_upcoming_window() {
        // Jan 1's window opens at 4:19 (jitter 19), so on-the-hour scans reach it at the 4:30 step;
        // Jul 1 opens at 4:29, reached at the 4:30 local step.
        let cases: [(&str, Vec<TimeZone>, &str, SignedDuration); 7] = [
            ("already inside the window applies now", vec![zone("UTC")], "2026-01-01T04:30:00Z", SignedDuration::ZERO),
            ("waits for the next window to open", vec![zone("UTC")], "2026-01-01T01:00:00Z", SignedDuration::from_mins(210)),
            // July: NY's 04:29 EDT open sits at 08:29 UTC (not 09:29), so the 08:30 step, 270m from 04:00 UTC.
            ("targets the DST-shifted window in summer", vec![zone("America/New_York")], "2026-07-01T04:00:00Z", SignedDuration::from_mins(270)),
            ("same-zone agents share one window", vec![zone("UTC"), zone("UTC"), zone("UTC")], "2026-01-01T00:00:00Z", SignedDuration::from_mins(270)),
            // Two UTC agents outrank the lone NY agent, so aim at UTC's 04:30 step (270m) not NY's.
            ("picks the window covering the most agents", vec![zone("UTC"), zone("UTC"), zone("America/New_York")], "2026-01-01T00:00:00Z", SignedDuration::from_mins(270)),
            // Neither window covers more than one, so take the earliest: UTC's 04:30 step (270m) beats NY's 09:30 UTC (570m).
            ("disjoint single zones take the earliest window", vec![zone("UTC"), zone("America/New_York")], "2026-01-01T00:00:00Z", SignedDuration::from_mins(270)),
            ("no agents applies immediately", vec![], "2026-01-01T12:00:00Z", SignedDuration::ZERO),
        ];
        for (desc, zones, now, expected) in cases {
            assert_eq!(wait_until_best_window(&zones, ts(now)), expected, "{desc}");
        }
    }

    #[test]
    fn missing_or_bad_timezone_falls_back_to_host_local() {
        let system = TimeZone::system();
        assert_eq!(resolve_zone(None).iana_name(), system.iana_name());
        assert_eq!(resolve_zone(Some("Definitely/NotAZone")).iana_name(), system.iana_name());
        assert_eq!(resolve_zone(Some("America/New_York")).iana_name(), Some("America/New_York"));
    }
}
