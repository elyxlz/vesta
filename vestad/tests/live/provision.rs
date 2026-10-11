use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use vesta_tests::{find_vestad, unique_agent, SERVER};

use super::common::{host_credentials_path, live_model};

const LIVE_READY_TIMEOUT_SECS: u64 = 600;

#[test]
fn provision_signs_in_a_real_agent() {
    let Some(credentials_path) = host_credentials_path() else {
        eprintln!("skipping live provision: CLAUDE_CREDENTIALS not set");
        return;
    };
    let credentials = std::fs::read_to_string(credentials_path).expect("read credentials");
    let name = unique_agent("live-provision");
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("provision.json");
    let config = serde_json::json!({
        "agent_name": name,
        "provider": {"kind": "claude", "credentials": credentials},
        "model": live_model(),
        "timezone": "UTC",
    });
    let mut file = std::fs::File::create(&path).expect("create");
    file.write_all(config.to_string().as_bytes())
        .expect("write");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).expect("chmod");

    let output = std::process::Command::new(find_vestad().expect("vestad"))
        .args(["provision", path.to_str().expect("utf8")])
        .env("HOME", SERVER.home_path())
        .output()
        .expect("run provision");
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(output.status.success(), "{stderr}");
    let lines: Vec<&str> = stdout.lines().collect();
    assert_eq!(lines.len(), 1, "stdout must be the link alone: {stdout}");
    assert!(lines[0].contains("/app#k="), "{}", lines[0]);
    assert!(
        !stdout.contains(&credentials) && !stderr.contains(&credentials),
        "the credential leaked into the output"
    );

    let client = SERVER.client();
    client
        .wait_until_alive(&name, LIVE_READY_TIMEOUT_SECS)
        .expect("the agent finishes first start");
    client.destroy_agent(&name).expect("cleanup");
}
