use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use vesta_tests::exec_in_container;

use super::common::{lock_live_agent_a, wait_for_file_contains, write_notification, E2E_FILES_DIR};

/// Per-step timeout for the agent to make observable progress.
const TASK_TIMEOUT: Duration = Duration::from_secs(300);

/// Proving the count is dead: the counting task appends a number roughly every 5s, so once the
/// file is unchanged for COUNT_STABLE_WINDOW (comfortably longer than that cadence) nothing is
/// appending anymore. We poll at COUNT_POLL_INTERVAL, fail fast the instant the count reaches 10
/// (the interrupt did not abort), and cap the whole check at COUNT_DEATH_TIMEOUT.
const COUNT_POLL_INTERVAL: Duration = Duration::from_secs(3);
const COUNT_STABLE_WINDOW: Duration = Duration::from_secs(15);
const COUNT_DEATH_TIMEOUT: Duration = Duration::from_secs(60);

/// Prove the negative: after the redirect ran, the counting task is dead. It must never reach 10
/// (a surviving turn or an orphaned `sleep && echo` appender would get there), and its file must
/// stop growing. Returns as soon as the file has been stable for COUNT_STABLE_WINDOW rather than
/// always blocking for a fixed grace period.
fn assert_counting_is_dead(container: &str, counting_file: &str) {
    let read = || {
        exec_in_container(
            container,
            &format!("cat {counting_file} 2>/dev/null || true"),
        )
        .unwrap_or_default()
    };
    let overall_deadline = Instant::now() + COUNT_DEATH_TIMEOUT;
    let mut last = read();
    let mut last_changed = Instant::now();
    loop {
        assert!(
            !last.contains("10"),
            "count reached 10 — the interrupt did not abort the counting task:\n{last}"
        );
        if last_changed.elapsed() >= COUNT_STABLE_WINDOW || Instant::now() >= overall_deadline {
            return;
        }
        thread::sleep(COUNT_POLL_INTERVAL);
        let current = read();
        if current != last {
            last = current;
            last_changed = Instant::now();
        }
    }
}

/// The real interrupt path, end to end with real Claude:
/// a slow multi-step task (count to 10 via file appends) is interrupted mid-flight by an
/// `interrupt: true` notification that redirects the agent to a different task. The original
/// task must be abandoned (count never reaches 10) and the new task must complete.
#[test]
fn interrupt_aborts_counting_and_runs_redirect_task() {
    let Some((_shared, container)) = lock_live_agent_a() else {
        return;
    };

    let uid = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
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
    let content_at_3 = wait_for_file_contains(&container, &counting_file, "3", TASK_TIMEOUT)
        .expect("counting reached 3");
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
    wait_for_file_contains(&container, &redirect_file, "interrupted", TASK_TIMEOUT)
        .expect("redirect file written");

    // The counting task must stay dead: never reach 10, and stop growing.
    assert_counting_is_dead(&container, &counting_file);
}

/// The other half of the preemption contract, and the #982 regression guard: when the main turn
/// is preempted, an already-running BACKGROUND subagent must survive and run to completion. The
/// default `preempt_mode = "message"` pre-sends the interrupt as a priority:"now" message, which
/// aborts only the turn; the old `interrupt()` control request (still used by `preempt_mode =
/// "interrupt"`) swept the CLI's task registry and killed every backgrounded subagent, so this
/// test would fail under that mode — it pins the default behavior against a silent regression.
///
/// The main agent launches a background subagent that slowly counts to 10 in its own file, then
/// counts in the foreground itself; an interrupting notification preempts the foreground turn.
/// The foreground count must die (preempt landed) while the background subagent's file still
/// reaches 10 (it was never swept).
#[test]
fn preempt_preserves_running_background_subagent() {
    let Some((_shared, container)) = lock_live_agent_a() else {
        return;
    };

    let uid = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let background_file = format!("{E2E_FILES_DIR}/bg-{uid}.txt");
    let foreground_file = format!("{E2E_FILES_DIR}/fg-{uid}.txt");
    let redirect_file = format!("{E2E_FILES_DIR}/instead-{uid}.txt");

    // One turn sets up both halves: a detached background subagent counting to 10, and the main
    // agent's own foreground count. The foreground count keeps the main turn open so the later
    // interrupt has a live turn to preempt; the "do NOT wait" clause stops the agent from
    // blocking on the subagent (which would leave the foreground file empty).
    write_notification(
        &container,
        &format!(
            "Do these two steps in order. \
             STEP 1: Use the Task tool to launch a BACKGROUND agent — set run_in_background to true and do NOT wait for it to finish. \
             Its instructions are: append the numbers 1 through 10, one number per line, to the file \"{background_file}\", \
             running `sleep 5` as its own separate command between appends, one bash command per number, never more than one number per command. \
             STEP 2: As soon as the background agent is launched, WITHOUT waiting for it, you yourself append the numbers 1 through 10, \
             one number per line, to the file \"{foreground_file}\", running `sleep 5` as its own command between appends, \
             one bash command per number, never more than one number per command."
        ),
        false,
    )
    .expect("write background+foreground notification");

    // Both halves must be genuinely mid-flight before the interrupt: the foreground count has
    // reached 3 (a live turn to preempt) and the background subagent has started (something to
    // preserve) but is nowhere near done.
    let foreground_at_3 = wait_for_file_contains(&container, &foreground_file, "3", TASK_TIMEOUT)
        .expect("foreground counting reached 3");
    assert!(
        !foreground_at_3.contains("10"),
        "agent wrote the whole foreground count at once; cannot exercise mid-turn preemption:\n{foreground_at_3}"
    );
    let background_started =
        wait_for_file_contains(&container, &background_file, "2", TASK_TIMEOUT)
            .expect("background subagent started counting");
    assert!(
        !background_started.contains("10"),
        "background subagent already finished before the interrupt; cannot prove it survived preemption:\n{background_started}"
    );

    // Preempt the foreground turn, explicitly leaving the background subagent alone so any death
    // is the CLI sweeping it, not the agent obeying a stop.
    write_notification(
        &container,
        &format!(
            "STOP your own counting to \"{foreground_file}\" immediately: do not append any more numbers to it and do not resume it later. \
             Leave the background agent alone — do NOT cancel, stop, or kill it; let it keep running. \
             Instead create the file \"{redirect_file}\" containing only the word: interrupted"
        ),
        true,
    )
    .expect("write interrupt notification");

    // The redirect must complete (the preempt landed) and the background subagent must reach 10
    // (it survived the preempt — the regression assertion).
    wait_for_file_contains(&container, &redirect_file, "interrupted", TASK_TIMEOUT)
        .expect("redirect file written");
    wait_for_file_contains(&container, &background_file, "10", TASK_TIMEOUT)
        .expect("background subagent survived the preempt and finished counting to 10");

    // And the foreground count the interrupt targeted must stay dead.
    assert_counting_is_dead(&container, &foreground_file);
}
