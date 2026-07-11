use std::time::{Duration, SystemTime, UNIX_EPOCH};

use super::common::{lock_live_agent_a, wait_for_file_contains, write_notification, E2E_FILES_DIR};

/// Basic file operations end to end against real claude. Create and modify share the same
/// notification -> file mechanism, so one conversation exercises both: the agent creates a file
/// with exact content from one notification, then appends to that same file from a second
/// notification without losing the original content.
#[test]
fn agent_notification_e2e_creates_then_modifies_file_via_vestad() {
    let Some((_shared, container)) = lock_live_agent_a() else {
        return;
    };

    let uid = format!(
        "{}",
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
    );
    let file = format!("{E2E_FILES_DIR}/file-{uid}.txt");
    let expected = format!("E2E content {uid}");

    write_notification(
        &container,
        &format!("Create the file \"{file}\" containing only:\n{expected}"),
        true,
    )
    .expect("write create notification");
    let created_content =
        wait_for_file_contains(&container, &file, &expected, Duration::from_secs(180))
            .expect("wait for created file");
    assert!(created_content.contains(&expected));

    write_notification(
        &container,
        &format!("Append the text \"--- APPENDED ---\" to the file \"{file}\""),
        true,
    )
    .expect("write modify notification");
    let modified_content =
        wait_for_file_contains(&container, &file, "APPENDED", Duration::from_secs(180))
            .expect("wait for modified file");
    assert!(
        modified_content.contains(&expected),
        "append must preserve the original content"
    );
    assert!(modified_content.contains("APPENDED"));
}
