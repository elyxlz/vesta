use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use vesta_tests::{find_vestad, is_up, unique_agent, TestAgent, FAKE_TOKEN, SERVER};

struct Outcome {
    success: bool,
    stdout: String,
    stderr: String,
}

fn provision(config: &serde_json::Value, mode: u32) -> Outcome {
    let dir = tempfile::tempdir().expect("tempdir");
    let path = dir.path().join("provision.json");
    let mut file = std::fs::File::create(&path).expect("create config");
    file.write_all(config.to_string().as_bytes())
        .expect("write config");
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(mode)).expect("chmod");
    let output = std::process::Command::new(find_vestad().expect("vestad binary"))
        .args(["provision", path.to_str().expect("utf8 path")])
        .env("HOME", SERVER.home_path())
        .output()
        .expect("run vestad provision");
    Outcome {
        success: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
    }
}

fn config(name: &str, credentials: &str) -> serde_json::Value {
    serde_json::json!({
        "agent_name": name,
        "provider": {"kind": "claude", "credentials": credentials},
        "timezone": "Europe/Rome",
    })
}

#[test]
fn a_rejected_credential_leaves_no_agent_behind() {
    let name = unique_agent("provision-bad");
    let outcome = provision(&config(&name, r#"{"not":"oauth"}"#), 0o600);
    assert!(!outcome.success);
    assert!(
        outcome.stdout.is_empty(),
        "no link on failure: {}",
        outcome.stdout
    );
    assert_eq!(
        SERVER.client().agent_status(&name).expect("status").status,
        "not_found"
    );
}

#[test]
fn an_existing_name_is_refused_and_left_alone() {
    let client = SERVER.client();
    let existing = TestAgent::create(&client, &unique_agent("provision-dup")).expect("create");
    let outcome = provision(&config(&existing.name, FAKE_TOKEN), 0o600);
    assert!(!outcome.success);
    assert!(
        outcome.stderr.contains("already exists"),
        "{}",
        outcome.stderr
    );
    assert!(is_up(
        &client.agent_status(&existing.name).expect("status").status
    ));
}

#[test]
fn a_readable_config_is_refused_before_anything_runs() {
    let name = unique_agent("provision-mode");
    let outcome = provision(&config(&name, FAKE_TOKEN), 0o644);
    assert!(!outcome.success);
    assert!(outcome.stderr.contains("chmod 600"), "{}", outcome.stderr);
}
