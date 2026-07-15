//! Choosing when to apply an auto-update so it disturbs the fewest agents.
//!
//! An update restarts every agent container at once (that invariant stays), so a single instant
//! must serve the whole fleet. We aim it at the upcoming 3-5am window that covers the most agents
//! in their own local time: agents sharing a timezone stack, and nearby timezones' windows overlap
//! and stack too. The update always lands within 24h (each zone hits 3-5am daily), just at the
//! least-disruptive moment.

use jiff::{tz::TimeZone, SignedDuration, Timestamp};

const WINDOW_START_HOUR: i8 = 3;
const WINDOW_END_HOUR: i8 = 5;
const SCAN_HORIZON_HOURS: i64 = 24;
const SCAN_STEP_MINUTES: i64 = 15;

/// Resolve an agent's reported IANA timezone name to a zone, falling back to the vestad host's
/// local zone when the agent reported none (pre-upstream-sync fleet) or the name doesn't parse.
/// Degrading to host-local keeps the update flowing rather than stalling on a missing timezone.
pub fn resolve_zone(name: Option<&str>) -> TimeZone {
    match name {
        Some(name) => TimeZone::get(name).unwrap_or_else(|_| TimeZone::system()),
        None => TimeZone::system(),
    }
}

/// Whether `at` falls inside the `[3:00, 5:00)` local window for `zone`.
fn in_window(zone: &TimeZone, at: Timestamp) -> bool {
    let hour = at.to_zoned(zone.clone()).hour();
    (WINDOW_START_HOUR..WINDOW_END_HOUR).contains(&hour)
}

fn count_in_window(zones: &[TimeZone], at: Timestamp) -> usize {
    zones.iter().filter(|zone| in_window(zone, at)).count()
}

/// How long to wait from `now` before applying the update so it lands in the upcoming 3-5am
/// window covering the most agents. Zero means apply now: either there are no agents to protect,
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
        let count = count_in_window(zones, now + SignedDuration::from_mins(offset_mins));
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
    fn in_window_utc_boundaries_are_half_open() {
        let utc = zone("UTC");
        assert!(!in_window(&utc, ts("2026-01-01T02:59:00Z")));
        assert!(in_window(&utc, ts("2026-01-01T03:00:00Z")));
        assert!(in_window(&utc, ts("2026-01-01T04:59:00Z")));
        assert!(!in_window(&utc, ts("2026-01-01T05:00:00Z")));
    }

    #[test]
    fn in_window_respects_offset_zone_in_winter() {
        // New York is UTC-5 in January, so 04:00 EST == 09:00 UTC.
        let ny = zone("America/New_York");
        assert!(in_window(&ny, ts("2026-01-01T09:00:00Z")));
        assert!(!in_window(&ny, ts("2026-01-01T06:00:00Z"))); // 01:00 EST
    }

    #[test]
    fn in_window_respects_dst_shift_in_summer() {
        // New York is UTC-4 in July (EDT): 03:00 EDT == 07:00 UTC is in-window, while 09:00 UTC ==
        // 05:00 EDT is out -- the very same 09:00 UTC instant that IS in-window in winter (04:00 EST,
        // asserted above), so the zone's DST offset is being applied, not a fixed one.
        let ny = zone("America/New_York");
        assert!(in_window(&ny, ts("2026-07-01T07:00:00Z")));
        assert!(!in_window(&ny, ts("2026-07-01T09:00:00Z")));
    }

    #[test]
    fn wait_until_best_window_picks_the_least_disruptive_upcoming_window() {
        let cases: [(&str, Vec<TimeZone>, &str, SignedDuration); 7] = [
            ("already inside the window applies now", vec![zone("UTC")], "2026-01-01T03:30:00Z", SignedDuration::ZERO),
            ("waits for the next window to open", vec![zone("UTC")], "2026-01-01T01:00:00Z", SignedDuration::from_hours(2)),
            // July: NY's 03:00 EDT window opens at 07:00 UTC (not 08:00), so 3h from 04:00 UTC.
            ("targets the DST-shifted window in summer", vec![zone("America/New_York")], "2026-07-01T04:00:00Z", SignedDuration::from_hours(3)),
            ("same-zone agents share one window", vec![zone("UTC"), zone("UTC"), zone("UTC")], "2026-01-01T00:00:00Z", SignedDuration::from_hours(3)),
            // Two UTC agents outrank the lone NY agent, so aim at UTC's 03:00 window (3h) not NY's.
            ("picks the window covering the most agents", vec![zone("UTC"), zone("UTC"), zone("America/New_York")], "2026-01-01T00:00:00Z", SignedDuration::from_hours(3)),
            // Neither window covers more than one, so take the earliest: UTC's 03:00 (3h) beats NY's 08:00 UTC (8h).
            ("disjoint single zones take the earliest window", vec![zone("UTC"), zone("America/New_York")], "2026-01-01T00:00:00Z", SignedDuration::from_hours(3)),
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
