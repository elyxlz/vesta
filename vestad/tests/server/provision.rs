use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use vesta_tests::{find_vestad, is_up, unique_agent, FAKE_TOKEN, SERVER};

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
fn provision_brings_up_a_signed_in_agent_and_prints_only_the_link() {
    let name = unique_agent("provision-ok");
    let outcome = provision(&config(&name, FAKE_TOKEN), 0o600);
    assert!(outcome.success, "stderr: {}", outcome.stderr);
    let lines: Vec<&str> = outcome.stdout.lines().collect();
    assert_eq!(
        lines.len(),
        1,
        "stdout must be the link alone: {}",
        outcome.stdout
    );
    assert!(
        (lines[0].starts_with("http://") || lines[0].starts_with("https://"))
            && lines[0].contains("/app#k="),
        "{}",
        lines[0]
    );
    assert!(
        !outcome.stderr.contains(FAKE_TOKEN),
        "a secret leaked to stderr"
    );
    let client = SERVER.client();
    assert!(is_up(&client.agent_status(&name).expect("status").status));
    client.destroy_agent(&name).expect("cleanup");
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
    let name = unique_agent("provision-dup");
    assert!(provision(&config(&name, FAKE_TOKEN), 0o600).success);
    let second = provision(&config(&name, FAKE_TOKEN), 0o600);
    assert!(!second.success);
    assert!(
        second.stderr.contains("already exists"),
        "{}",
        second.stderr
    );
    let client = SERVER.client();
    assert!(is_up(&client.agent_status(&name).expect("status").status));
    client.destroy_agent(&name).expect("cleanup");
}

#[test]
fn a_readable_config_is_refused_before_anything_runs() {
    let name = unique_agent("provision-mode");
    let outcome = provision(&config(&name, FAKE_TOKEN), 0o644);
    assert!(!outcome.success);
    assert!(outcome.stderr.contains("chmod 600"), "{}", outcome.stderr);
}
