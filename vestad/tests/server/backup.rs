use std::time::{Duration, Instant};

use vesta_tests::types::BackupType;
use vesta_tests::{
    agent_container_name, exec_in_container, is_up, unique_agent, TestAgent, SERVER,
    SHARED_RO_AGENT,
};

const EVENTS_DB_POLL_TIMEOUT: Duration = Duration::from_secs(60);
const EVENTS_DB_POLL_INTERVAL: Duration = Duration::from_millis(500);

/// Poll until the agent's events.db exists. CI runners are slow under contention, and the
/// db is created only once the agent process has actually started inside the container.
fn wait_for_events_db(cname: &str) {
    let deadline = Instant::now() + EVENTS_DB_POLL_TIMEOUT;
    loop {
        if exec_in_container(cname, "test -f /root/agent/data/events.db").is_ok() {
            return;
        }
        if Instant::now() >= deadline {
            panic!(
                "events.db did not appear in {cname} within {}s",
                EVENTS_DB_POLL_TIMEOUT.as_secs()
            );
        }
        std::thread::sleep(EVENTS_DB_POLL_INTERVAL);
    }
}

/// The container's docker identity and start time, for asserting a backup never restarts it.
fn container_id_and_started_at(cname: &str) -> String {
    let output = std::process::Command::new("docker")
        .args(["inspect", "--format", "{{.Id}} {{.State.StartedAt}} {{.State.Status}}", cname])
        .output()
        .expect("docker inspect runs");
    assert!(output.status.success(), "docker inspect {cname} failed");
    String::from_utf8_lossy(&output.stdout).trim().to_string()
}

#[test]
fn backup_does_not_restart_running_agent() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-norestart")).unwrap();
    let cname = agent_container_name(&agent.name);
    wait_for_events_db(&cname);

    let before = container_id_and_started_at(&cname);
    assert!(before.ends_with("running"), "agent must be running before backup, got {before}");

    let backup = c.create_backup(&agent.name).unwrap();

    let after = container_id_and_started_at(&cname);
    assert_eq!(
        before, after,
        "a backup must never stop or restart the container (same id, StartedAt, and status)"
    );

    c.delete_backup(&agent.name, &backup.id).ok();
}

#[test]
fn backup_of_stopped_agent_succeeds() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-stopped")).unwrap();

    c.stop_agent(&agent.name).unwrap();
    let backup = c.create_backup(&agent.name).unwrap();
    assert!(backup.size > 0);

    let st = c.agent_status(&agent.name).unwrap();
    assert!(!is_up(&st.status), "backup must leave a stopped agent stopped, got {}", st.status);

    c.delete_backup(&agent.name, &backup.id).ok();
}

#[test]
fn backup_create() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-create")).unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    assert_eq!(backup.agent_name, agent.name);
    assert_eq!(backup.backup_type, BackupType::Manual);
    assert!(backup.size > 0);
    assert!(!backup.id.is_empty());

    c.delete_backup(&agent.name, &backup.id).ok();
}

#[test]
fn backup_list() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-list")).unwrap();

    let b1 = c.create_backup(&agent.name).unwrap();
    let b2 = c.create_backup(&agent.name).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(backups.len() >= 2);
    assert!(backups[0].created_at >= backups[1].created_at);

    c.delete_backup(&agent.name, &b1.id).ok();
    c.delete_backup(&agent.name, &b2.id).ok();
}

#[test]
fn backup_list_empty() {
    let c = SERVER.client();
    let backups = c.list_backups(&SHARED_RO_AGENT).unwrap();
    assert!(backups.is_empty());
}

#[test]
fn backup_restore() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-restore")).unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert!(
        is_up(&st.status),
        "expected up after restore, got {}",
        st.status
    );

    let backups = c.list_backups(&agent.name).unwrap();
    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

/// The pipeline crosses four lossy seams (docker export, restic --stdin, restic dump,
/// docker import): assert the data actually comes back, not just that the container starts.
#[test]
fn backup_restore_round_trips_data() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-roundtrip")).unwrap();
    let cname = agent_container_name(&agent.name);
    wait_for_events_db(&cname);

    exec_in_container(&cname, "echo roundtrip-marker-abc123 > /root/marker.txt")
        .expect("write marker");
    exec_in_container(
        &cname,
        "cat > /root/roundtrip_insert.py <<'EOF'\n\
import sqlite3\n\
conn = sqlite3.connect(\"/root/agent/data/events.db\")\n\
conn.execute(\"INSERT INTO events (ts, data) VALUES (?, ?)\", (\"2026-01-01T00:00:00Z\", '{\"type\": \"test\", \"marker\": \"roundtrip-test-event\"}'))\n\
conn.commit()\n\
EOF\n\
/root/agent/.venv/bin/python3 /root/roundtrip_insert.py",
    )
    .expect("seed events.db row");

    let backup = c.create_backup(&agent.name).unwrap();

    // Overwrite the live marker so the restore, not the still-running container, is what
    // the assertion below depends on.
    exec_in_container(&cname, "echo overwritten > /root/marker.txt").expect("overwrite marker");

    c.restore_backup(&agent.name, &backup.id).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert!(
        is_up(&st.status),
        "expected up after restore, got {}",
        st.status
    );

    let marker =
        exec_in_container(&cname, "cat /root/marker.txt").expect("read marker after restore");
    assert_eq!(
        marker.trim(),
        "roundtrip-marker-abc123",
        "marker file must round-trip through backup/restore"
    );

    let check = exec_in_container(
        &cname,
        "cat > /root/roundtrip_check.py <<'EOF'\n\
import sqlite3\n\
conn = sqlite3.connect(\"/root/agent/data/events.db\")\n\
count = conn.execute(\"SELECT COUNT(*) FROM events WHERE data LIKE '%roundtrip-test-event%'\").fetchone()[0]\n\
integrity = conn.execute(\"PRAGMA integrity_check\").fetchone()[0]\n\
print(f\"{count} {integrity}\")\n\
EOF\n\
/root/agent/.venv/bin/python3 /root/roundtrip_check.py",
    )
    .expect("check events.db after restore");
    assert_eq!(
        check.trim(),
        "1 ok",
        "the inserted events.db row must round-trip and the restored db must pass integrity_check"
    );

    let backups = c.list_backups(&agent.name).unwrap();
    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_restore_creates_safety_snapshot() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-safety")).unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    let pre_restore = backups
        .iter()
        .find(|b| b.backup_type == BackupType::PreRestore);
    assert!(
        pre_restore.is_some(),
        "expected a pre-restore safety backup"
    );

    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_delete() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("bk-delete")).unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.delete_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(!backups.iter().any(|b| b.id == backup.id));
}

#[test]
fn backup_delete_nonexistent_fails() {
    let c = SERVER.client();
    let result = c.delete_backup(&SHARED_RO_AGENT, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
}

#[test]
fn backup_restore_nonexistent_fails() {
    let c = SERVER.client();
    let result = c.restore_backup(&SHARED_RO_AGENT, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
}
