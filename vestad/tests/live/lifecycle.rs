use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use super::common::{
    create_file_request, lock_live_agent_a, wait_for_container_running, wait_for_file_contains,
    write_notification, E2E_FILES_DIR,
};
use vesta_tests::docker_cmd;

fn started_at(container: &str) -> String {
    docker_cmd(&["inspect", "--format", "{{.State.StartedAt}}", container]).unwrap_or_default()
}

/// End to end against real claude: the agent's `restart_vesta` MCP tool restarts the container
/// THROUGH vestad (the agent no longer self-kills — under the on-failure policy a clean self-exit
/// would just stay down). Tell the agent to call the tool, confirm the container actually restarted
/// (its `StartedAt` advances — a vestad `docker restart`, not a policy-driven one, so `RestartCount`
/// is intentionally unchanged), then confirm the agent comes back and still does real work.
#[test]
fn agent_restart_vesta_tool_restarts_through_vestad() {
    let Some((_shared, container)) = lock_live_agent_a() else {
        return;
    };

    let started_before = started_at(&container);
    assert!(
        !started_before.is_empty(),
        "agent container should be running before the test"
    );

    write_notification(
        &container,
        "Use the restart_vesta tool right now to restart your container. Do it immediately, no need to ask or explain.",
        true,
    )
    .expect("write restart notification");

    // The container must actually restart: vestad does a graceful docker restart (stop timeout +
    // start), so its StartedAt timestamp advances. If restart_vesta were still a self-exit, the
    // on-failure policy would leave the container down and StartedAt would never change.
    let deadline = Instant::now() + Duration::from_secs(180);
    loop {
        let now = started_at(&container);
        if !now.is_empty() && now != started_before {
            break;
        }
        if Instant::now() >= deadline {
            panic!("container StartedAt did not advance — restart_vesta did not restart through vestad");
        }
        std::thread::sleep(Duration::from_secs(3));
    }

    // The agent must come back and still do real work after the vestad-driven restart.
    wait_for_container_running(&container, Duration::from_secs(120))
        .expect("container running after restart");
    let uid = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs();
    let file = format!("{E2E_FILES_DIR}/restarted-{uid}.txt");
    write_notification(&container, &create_file_request(&file, "BACK"), true)
        .expect("write post-restart probe");
    wait_for_file_contains(&container, &file, "BACK", Duration::from_secs(300))
        .expect("agent must process work after the restart");
}
