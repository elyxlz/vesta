use std::time::{Duration, SystemTime, UNIX_EPOCH};

use vesta_tests::exec_in_container;

use super::common::{setup_live_agent, write_notification, wait_for_file_contains, E2E_FILES_DIR};

#[test]
fn agent_notification_e2e_creates_file_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-create", true, true, None) else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let created = format!("{E2E_FILES_DIR}/single-{uid}.txt");
    let expected = format!("E2E content {uid}");

    write_notification(
        &container,
        &format!("Create the file \"{created}\" containing only:\n{expected}"),
        true,
    )
    .expect("write create notification");

    let created_content = wait_for_file_contains(&container, &created, &expected, Duration::from_secs(180))
        .expect("wait for created file");
    assert!(created_content.contains(&expected));
}

#[test]
fn agent_notification_e2e_modifies_file_via_vestad() {
    let Some((_agent, container)) = setup_live_agent("test-e2e-modify", true, true, None) else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let modified = format!("{E2E_FILES_DIR}/modify-{uid}.txt");

    exec_in_container(&container, &format!("printf '%s\n' 'original content' > {modified}"))
        .expect("seed file");
    write_notification(
        &container,
        &format!("Append the text \"--- APPENDED ---\" to the file \"{modified}\""),
        true,
    )
    .expect("write modify notification");

    let modified_content = wait_for_file_contains(&container, &modified, "APPENDED", Duration::from_secs(180))
        .expect("wait for modified file");
    assert!(modified_content.contains("original content"));
    assert!(modified_content.contains("APPENDED"));
}
