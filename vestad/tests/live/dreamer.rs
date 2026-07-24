use std::thread;
use std::time::{Duration, Instant};

use vesta_tests::exec_in_container;

use super::common::{
    create_file_request, lock_live_agent_b, wait_for_file_contains, write_notification,
    E2E_FILES_DIR,
};

/// Poll a container shell command until its stdout contains `needle`, or time out.
fn wait_for_exec_contains(
    container: &str,
    script: &str,
    needle: &str,
    timeout: Duration,
) -> Result<String, String> {
    let deadline = Instant::now() + timeout;
    loop {
        let out = exec_in_container(container, script).unwrap_or_default();
        if out.contains(needle) {
            return Ok(out);
        }
        if Instant::now() >= deadline {
            return Err(format!(
                "timed out waiting for `{script}` to contain {needle}"
            ));
        }
        thread::sleep(Duration::from_secs(3));
    }
}

const STATE_JSON_PATH: &str = "/root/agent/data/state.json";

/// Read the persisted Claude session id. It lives as a field inside `state.json` (the standalone
/// `session_id` file is legacy), so pull it out with the container's python rather than `cat`.
fn read_session_id(container: &str) -> String {
    exec_in_container(
        container,
        &format!(
            "python3 -c \"import json; print(json.load(open('{STATE_JSON_PATH}'))['session_id'])\""
        ),
    )
    .expect("read session_id from state.json")
    .trim()
    .to_string()
}

/// End-to-end of the nightly dreamer's finalize step against real claude. The finalize is two
/// tool calls: `mark_dreamer_complete` records the run, then `compact_context(restart=true)` does
/// the work, which must (1) compact the live conversation in place via a real `/compact` (an
/// `isCompactSummary` line lands in the SAME session transcript), and (2) restart the agent while
/// KEEPING the session id, so the agent resumes the compacted conversation rather than waking up on
/// a blank slate. This is the behavior that replaced the old hard session reset.
#[test]
fn dreamer_complete_compacts_in_place_and_restart_resumes_the_session() {
    let Some((_shared, container)) = lock_live_agent_b() else {
        return;
    };

    let session_id_before = read_session_id(&container);
    assert!(
        !session_id_before.is_empty() && session_id_before != "None",
        "agent should have a persisted session id before the dream finalizes"
    );

    // Drive only the finalize step (not a full multi-minute dream): mark_dreamer_complete just
    // records the run, so the agent must then call compact_context(restart=true) to compact in
    // place and restart into the resumed session. The drain compacts at the next idle point.
    write_notification(
        &container,
        "Finalize tonight's dream now in two steps, and do nothing else (no full dream): first call your mark_dreamer_complete tool, then call your compact_context tool with restart set to true and a short prompt describing how to summarize this conversation.",
        true,
    )
    .expect("write dream finalize notification");

    // (1) Compaction really happened: claude writes an isCompactSummary line into the SAME
    // session transcript (manual /compact rewrites in place; resume keeps working).
    let transcript_glob = format!("/root/.claude/projects/*/{session_id_before}.jsonl");
    wait_for_exec_contains(
        &container,
        &format!("grep -l isCompactSummary {transcript_glob} 2>/dev/null || true"),
        ".jsonl",
        Duration::from_secs(300),
    )
    .expect("expected an isCompactSummary line in the session transcript (real /compact ran)");

    // (2) The agent restarts and RESUMES: a passive task is delivered only once the agent is idle
    // again after the restart, so the marker's appearance proves it came back alive on a resumed
    // session. (Passive notifications survive the restart; the monitor loop flushes them when idle.)
    let marker = format!("{E2E_FILES_DIR}/dream-resumed.txt");
    write_notification(
        &container,
        &create_file_request(&marker, "DREAM_RESUMED"),
        false,
    )
    .expect("write resume marker task");
    wait_for_file_contains(
        &container,
        &marker,
        "DREAM_RESUMED",
        Duration::from_secs(300),
    )
    .expect("agent did not come back alive after the dreamer restart");

    // The restart kept the session id: it resumed the compacted conversation, it did not reset.
    let session_id_after = read_session_id(&container);
    assert_eq!(
        session_id_before, session_id_after,
        "nightly restart must RESUME the compacted session (same session id), not hard-reset it"
    );
}
