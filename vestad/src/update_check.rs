const RELEASES_API_URL: &str = "https://api.github.com/repos/elyxlz/vesta/releases/latest";
const USER_AGENT: &str = "vestad-update-check";
pub const CHECK_INTERVAL_SECS: u64 = 6 * 60 * 60;
const CURL_TIMEOUT_SECS: &str = "10";

#[derive(Clone, Debug)]
pub struct UpdateInfo {
    pub current: String,
    pub latest: String,
    pub update_available: bool,
}

fn current_version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

fn parse_semver(raw: &str) -> Option<(u32, u32, u32)> {
    let trimmed = raw.trim().trim_start_matches('v');
    let mut parts = trimmed.split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next()?.parse().ok()?;
    // strip any pre-release/build suffix from patch
    let patch_raw = parts.next()?;
    let patch_clean: String = patch_raw.chars().take_while(|c| c.is_ascii_digit()).collect();
    let patch = patch_clean.parse().ok()?;
    Some((major, minor, patch))
}

fn fetch_latest_tag() -> Result<String, String> {
    let output = std::process::Command::new("curl")
        .args([
            "-fsSL",
            "--max-time",
            CURL_TIMEOUT_SECS,
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            &format!("User-Agent: {}", USER_AGENT),
            RELEASES_API_URL,
        ])
        .output()
        .map_err(|e| format!("curl failed: {}", e))?;

    if !output.status.success() {
        return Err(format!(
            "curl exited with status {}",
            output.status.code().unwrap_or(-1)
        ));
    }

    let body = String::from_utf8(output.stdout).map_err(|e| format!("invalid utf8: {}", e))?;
    let json: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("json parse failed: {}", e))?;

    let tag = json
        .get("tag_name")
        .and_then(|v| v.as_str())
        .ok_or_else(|| "missing tag_name in release response".to_string())?;

    Ok(tag.to_string())
}

pub fn check_once() -> Result<UpdateInfo, String> {
    let latest_tag = fetch_latest_tag()?;
    let current = current_version().to_string();

    let update_available = match (parse_semver(&current), parse_semver(&latest_tag)) {
        (Some(cur), Some(lat)) => lat > cur,
        _ => false,
    };

    Ok(UpdateInfo {
        current,
        latest: latest_tag.trim_start_matches('v').to_string(),
        update_available,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_semver_plain() {
        assert_eq!(parse_semver("0.1.2"), Some((0, 1, 2)));
    }

    #[test]
    fn parse_semver_v_prefix() {
        assert_eq!(parse_semver("v1.2.3"), Some((1, 2, 3)));
    }

    #[test]
    fn parse_semver_with_suffix() {
        assert_eq!(parse_semver("v1.2.3-rc.1"), Some((1, 2, 3)));
    }

    #[test]
    fn parse_semver_invalid() {
        assert_eq!(parse_semver("not-a-version"), None);
        assert_eq!(parse_semver("1.2"), None);
    }

    #[test]
    fn semver_comparison() {
        assert!(parse_semver("v0.2.0").unwrap() > parse_semver("v0.1.9").unwrap());
        assert!(parse_semver("v1.0.0").unwrap() > parse_semver("v0.9.9").unwrap());
        assert!(parse_semver("v0.1.10").unwrap() > parse_semver("v0.1.9").unwrap());
    }
}
