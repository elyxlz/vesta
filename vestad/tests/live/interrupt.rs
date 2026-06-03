use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use vesta_tests::exec_in_container;

use super::common::{lock_shared_live_agent, wait_for_file_contains, write_notification, E2E_FILES_DIR};

/// Per-step timeout for the agent to make observable progress.
const TASK_TIMEOUT: Duration = Duration::from_secs(240);

/// How long the count must keep NOT reaching 10 after the redirect task completed.
/// The counting task appends a number every ~5s, so if the interrupt failed (the counting
/// turn survived, or an orphaned tool process kept running) it would reach 10 well inside
/// this window.
const POST_REDIRECT_GRACE: Duration = Duration::from_secs(45);

/// The real interrupt path, end to end with real Claude:
/// a slow multi-step task (count to 10 via file appends) is interrupted mid-flight by an
/// `interrupt: true` notification that redirects the agent to a different task. The original
/// task must be abandoned (count never reaches 10) and the new task must complete.
#[test]
fn interrupt_aborts_counting_and_runs_redirect_task() {
    let Some((_shared, container)) = lock_shared_live_agent() else {
        return;
    };

    let uid = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
    let counting_file = format!("{E2E_FILES_DIR}/count-{uid}.txt");
    let redirect_file = format!("{E2E_FILES_DIR}/instead-{uid}.txt");

    // Task 1: slow, observable, multi-step — one append per number, 5s apart, so the
    // interrupt has a wide window to land in.
    write_notification(
        &container,
        &format!(
            "Count from 1 to 10 by appending numbers to the file \"{counting_file}\". \
             Append exactly ONE number per line, using a SEPARATE bash command for each number, \
             and run `sleep 5` as its own command between appends. \
             Never write more than one number in a single command."
        ),
        true,
    )
    .expect("write counting notification");

    // The task is genuinely mid-flight once the file contains 3.
    let content_at_3 =
        wait_for_file_contains(&container, &counting_file, "3", TASK_TIMEOUT).expect("counting reached 3");
    assert!(
        !content_at_3.contains("10"),
        "agent wrote the whole count at once instead of one number at a time; cannot exercise interruption:\n{content_at_3}"
    );

    // Task 2, marked interrupt: abandon counting, do something else instead.
    write_notification(
        &container,
        &format!(
            "STOP counting immediately. Do not append any more numbers to \"{counting_file}\", \
             do not finish the count, and do not come back to it later. \
             Instead create the file \"{redirect_file}\" containing only the word: interrupted"
        ),
        true,
    )
    .expect("write interrupt notification");

    // The redirect task must complete.
    wait_for_file_contains(&container, &redirect_file, "interrupted", TASK_TIMEOUT).expect("redirect file written");

    // Prove the negative: counting stays dead. If the interrupted turn (or an orphaned
    // `sleep && echo` process) were still appending, it would hit 10 within this window.
    thread::sleep(POST_REDIRECT_GRACE);

    let count_content = exec_in_container(&container, &format!("cat {counting_file} 2>/dev/null || true")).unwrap_or_default();
    assert!(
        !count_content.contains("10"),
        "count reached 10 — the interrupt did not abort the counting task:\n{count_content}"
    );
}
