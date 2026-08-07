//! The one owner of the ipwho.is geo lookup: given a public client IP, resolve a coarse
//! "City, Country" label for the device roster. Any failure yields None; the caller treats a missing
//! location as simply unknown.

use std::net::IpAddr;
use std::time::Duration;

use serde::Deserialize;

const IPWHO_BASE: &str = "https://ipwho.is";
const GEO_TIMEOUT_SECS: u64 = 5;

#[derive(Debug, Deserialize)]
struct IpwhoResponse {
    #[serde(default)]
    success: bool,
    #[serde(default)]
    city: Option<String>,
    #[serde(default)]
    country: Option<String>,
}

fn parse_ipwho(body: &str) -> Option<String> {
    let parsed: IpwhoResponse = serde_json::from_str(body).ok()?;
    if !parsed.success {
        return None;
    }
    let city = parsed.city.filter(|value| !value.is_empty())?;
    let country = parsed.country.filter(|value| !value.is_empty())?;
    Some(format!("{city}, {country}"))
}

/// Resolve a coarse "City, Country" for a public IP. None on any network or shape failure.
pub(crate) async fn lookup(client: &reqwest::Client, ip: IpAddr) -> Option<String> {
    let url = format!("{IPWHO_BASE}/{ip}");
    let response = client
        .get(&url)
        .timeout(Duration::from_secs(GEO_TIMEOUT_SECS))
        .send()
        .await
        .ok()?;
    if !response.status().is_success() {
        return None;
    }
    let body = response.text().await.ok()?;
    parse_ipwho(&body)
}

#[cfg(test)]
mod tests {
    use super::parse_ipwho;

    #[test]
    fn parses_a_well_formed_body() {
        let body = r#"{"success":true,"city":"London","country":"United Kingdom"}"#;
        assert_eq!(parse_ipwho(body).as_deref(), Some("London, United Kingdom"));
    }

    #[test]
    fn rejects_a_failure_body() {
        let body = r#"{"success":false,"message":"reserved range"}"#;
        assert_eq!(parse_ipwho(body), None);
    }

    #[test]
    fn rejects_malformed_json() {
        assert_eq!(parse_ipwho("{ not json"), None);
    }

    #[test]
    fn rejects_missing_or_empty_fields() {
        assert_eq!(parse_ipwho(r#"{"success":true,"country":"France"}"#), None);
        assert_eq!(parse_ipwho(r#"{"success":true,"city":"","country":"France"}"#), None);
    }
}
