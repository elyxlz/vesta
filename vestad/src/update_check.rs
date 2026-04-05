pub const CHECK_INTERVAL_SECS: u64 = 6 * 60 * 60;
const FETCH_TIMEOUT_SECS: u64 = 10;

#[derive(Clone, Debug)]
pub struct UpdateInfo {
    pub current: String,
    pub latest: String,
    pub update_available: bool,
}

pub fn check_once() -> Result<UpdateInfo, String> {
    let latest = vesta_common::fetch_latest_release_tag(Some(FETCH_TIMEOUT_SECS))
        .ok_or_else(|| "failed to fetch latest release".to_string())?;
    let current = env!("CARGO_PKG_VERSION").to_string();
    let update_available = vesta_common::version_less_than(&current, &latest);

    Ok(UpdateInfo {
        current,
        latest,
        update_available,
    })
}
