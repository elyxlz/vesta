use std::time::{Duration, Instant};

use vesta_tests::{download_latest_released_vestad, find_vestad, unique_user, TestServerBuilder, FAKE_TOKEN, exec_in_container};

use super::common::{agent_container_name, wait_for_agent_visible};

#[test]
#[cfg(target_os = "linux")]
fn latest_released_vestad_upgrades_to_current_and_agent_git_state_is_valid() {
    let released = download_latest_released_vestad().expect("download released vestad");
    let current = find_vestad().expect("find current vestad");
    let home = tempfile::TempDir::new().expect("tmp home");
    let user = unique_user("upgradee");
    let agent_name = "upgrade-agent";

    let mut released_server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(released.bin_path.clone())
        .start()
        .expect("start released vestad");

    let released_client = released_server.client();
    let created_name = released_client
        .create_agent(agent_name, false)
        .expect("create agent under released vestad");
    assert_eq!(created_name, agent_name);

    released_client
        .inject_token(agent_name, FAKE_TOKEN)
        .expect("inject fake token");
    let initial_status = released_client
        .agent_status(agent_name)
        .expect("status under released vestad");
    assert_ne!(initial_status.status, "not_found");

    let old_container = agent_container_name(&user, agent_name).expect("find initial container");
    released_server.shutdown();
    drop(released_server);

    let upgraded_server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(current)
        .start()
        .expect("start current vestad");
    let upgraded_client = upgraded_server.client();

    let deadline = Instant::now() + Duration::from_secs(60);
    wait_for_agent_visible(deadline, || {
        let status = upgraded_client.agent_status(agent_name)?;
        Ok(status.status != "not_found")
    })
    .expect("agent should remain visible after upgrade");

    upgraded_client
        .restart_agent(agent_name)
        .expect("restart agent after upgrade");
    let upgraded_status = upgraded_client
        .agent_status(agent_name)
        .expect("status after upgrade");
    assert_ne!(upgraded_status.status, "not_found");

    let new_container = agent_container_name(&user, agent_name).expect("find upgraded container");
    assert!(
        !new_container.is_empty(),
        "container name should still resolve after upgrade"
    );
    assert!(
        new_container == old_container || !new_container.is_empty(),
        "container may be rebuilt during reconciliation, but it must remain managed"
    );

    let top = exec_in_container(&new_container, "git -C ~ rev-parse --show-toplevel")
        .expect("git top-level");
    assert_eq!(top, "/root");

    let branch = exec_in_container(&new_container, "git -C ~ branch --show-current")
        .expect("git branch");
    assert_eq!(branch, agent_name);

    exec_in_container(&new_container, "test -d /root/agent").expect("agent dir exists");

    let sparse = exec_in_container(&new_container, "git -C ~ sparse-checkout list")
        .expect("sparse-checkout list");
    assert!(
        sparse.lines().any(|line| line.trim().starts_with("agent/")),
        "expected sparse-checkout to include agent/ paths, got: {sparse}"
    );

    let porcelain = exec_in_container(&new_container, "git -C ~ status --porcelain --untracked-files=all")
        .expect("git status porcelain");
    for line in porcelain.lines() {
        let state = line.get(0..2).unwrap_or("");
        assert!(
            !matches!(state, "UU" | "AA" | "DD" | "AU" | "UA" | "DU" | "UD"),
            "unexpected unmerged git state after upgrade from {}: {}",
            released.tag,
            porcelain
        );
    }

    let ancestry = exec_in_container(
        &new_container,
        r#"source /run/vestad-env
set -euo pipefail
test -n "${VESTA_UPSTREAM_REF:-}"
git -C ~ fetch --depth 1 origin "$VESTA_UPSTREAM_REF"
git -C ~ merge-base --is-ancestor FETCH_HEAD HEAD
printf 'ok\n'"#,
    )
    .expect("upstream ancestry check");
    assert_eq!(ancestry, "ok", "expected HEAD to descend from upstream ref {}", released.tag);
}
