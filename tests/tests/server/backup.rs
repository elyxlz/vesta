use vesta_tests::{TestAgent, SERVER, is_up};
use vesta_tests::types::BackupType;

#[test]
fn backup_create() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-create").unwrap();

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
    let agent = TestAgent::create(&c, "test-backup-list").unwrap();

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
    let agent = TestAgent::create(&c, "test-backup-empty").unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(backups.is_empty());
    drop(agent);
}

#[test]
fn backup_restore() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-restore").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let st = c.agent_status(&agent.name).unwrap();
    assert!(is_up(&st.status), "expected up after restore, got {}", st.status);

    let backups = c.list_backups(&agent.name).unwrap();
    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_restore_creates_safety_snapshot() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-safety").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.restore_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    let pre_restore = backups
        .iter()
        .find(|b| b.backup_type == BackupType::PreRestore);
    assert!(pre_restore.is_some(), "expected a pre-restore safety backup");

    for b in &backups {
        c.delete_backup(&agent.name, &b.id).ok();
    }
}

#[test]
fn backup_delete() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-delete").unwrap();

    let backup = c.create_backup(&agent.name).unwrap();
    c.delete_backup(&agent.name, &backup.id).unwrap();

    let backups = c.list_backups(&agent.name).unwrap();
    assert!(!backups.iter().any(|b| b.id == backup.id));
}

#[test]
fn backup_delete_nonexistent_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-del-bad").unwrap();

    let result = c.delete_backup(&agent.name, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
    drop(agent);
}

#[test]
fn backup_restore_nonexistent_fails() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, "test-backup-res-bad").unwrap();

    let result = c.restore_backup(&agent.name, "vesta-backup:fake-manual-20260101-000000");
    assert!(result.is_err());
    drop(agent);
}
