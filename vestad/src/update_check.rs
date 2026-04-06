pub const CHECK_INTERVAL_SECS: u64 = 6 * 60 * 60;
const FETCH_TIMEOUT_SECS: u64 = 10;

const GITHUB_RELEASES_LATEST_URL: &str =
    "https://api.github.com/repos/elyxlz/vesta/releases/latest";

#[derive(Clone, Debug)]
pub struct UpdateInfo {
    pub current: String,
    pub latest: String,
    pub update_available: bool,
}

pub fn check_once() -> Result<UpdateInfo, String> {
    let latest = fetch_latest_release_tag(Some(FETCH_TIMEOUT_SECS))
        .ok_or_else(|| "failed to fetch latest release".to_string())?;
    let current = env!("CARGO_PKG_VERSION").to_string();
    let update_available = version_less_than(&current, &latest);

    Ok(UpdateInfo {
        current,
        latest,
        update_available,
    })
}

fn version_less_than(a: &str, b: &str) -> bool {
    let parse = |v: &str| -> Vec<u64> {
        v.split('.').filter_map(|s| s.parse().ok()).collect()
    };
    parse(a) < parse(b)
}

fn fetch_latest_release_tag(timeout_secs: Option<u64>) -> Option<String> {
    let mut args: Vec<String> = vec![
        "-fsSL".into(),
        "-H".into(),
        "Accept: application/vnd.github+json".into(),
        "-H".into(),
        "User-Agent: vesta-release-check".into(),
    ];
    if let Some(t) = timeout_secs {
        args.push("--connect-timeout".into());
        args.push(t.to_string());
        args.push("--max-time".into());
        args.push(t.to_string());
    }
    args.push(GITHUB_RELEASES_LATEST_URL.into());

    let output = std::process::Command::new("curl")
        .args(&args)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }

    let body = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = serde_json::from_str(&body).ok()?;
    let tag = data.get("tag_name")?.as_str()?.trim().trim_start_matches('v');
    if tag.is_empty() {
        None
    } else {
        Some(tag.to_string())
    }
}
