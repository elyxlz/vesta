use vesta_tests::{
    TestAgent, TestServerBuilder, SERVER, SHARED_RO_AGENT, agent_container_name, docker_cmd,
    find_vestad, inject_fake_token, is_up, unique_agent,
};

#[test]
fn create_and_list() {
    let c = SERVER.client();
    let list = c.list_agents().unwrap();
    let name: &str = &SHARED_RO_AGENT;
    assert!(list.iter().any(|a| a.name == name));
}

#[test]
fn create_duplicate_fails() {
    let c = SERVER.client();
    let result = c.create_agent(&SHARED_RO_AGENT);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("already exists"), "unexpected error: {err}");
}

#[test]
fn status_not_found() {
    let c = SERVER.client();
    let status = c.agent_status("nonexistent-agent-xyz").unwrap();
    assert_eq!(status.status, "not_found");
}

#[test]
fn start_stop_restart() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("start-stop")).unwrap();

    let desired = |name: &str| read_settings(SERVER.home_path())["agents"][name]["user_desired"].clone();

    c.start_agent(&agent.name).unwrap();
    c.wait_until_running(&agent.name, 60)
        .expect("agent should come up after start");
    assert_eq!(desired(&agent.name), "running", "start must record user_desired=running");

    // stop is asynchronous — wait for the container to wind down rather than reading
    // status immediately (the immediate read raced the still-running container).
    c.stop_agent(&agent.name).unwrap();
    c.wait_until_stopped(&agent.name, 60)
        .expect("agent should wind down after stop");
    assert_eq!(desired(&agent.name), "stopped", "stop must record user_desired=stopped (survives reboots)");

    c.start_agent(&agent.name).unwrap();
    c.restart_agent(&agent.name).unwrap();
    c.wait_until_running(&agent.name, 60)
        .expect("agent should be up after restart");
    assert_eq!(desired(&agent.name), "running", "restart must record user_desired=running");
}

#[test]
fn destroy_removes_agent() {
    let c = SERVER.client();
    let name = c.create_agent(&unique_agent("destroy")).unwrap();
    c.destroy_agent(&name).unwrap();
    let st = c.agent_status(&name).unwrap();
    assert_eq!(st.status, "not_found");
}

#[test]
fn destroy_stops_running_agent() {
    let c = SERVER.client();
    let name = c.create_agent(&unique_agent("destroy-run")).unwrap();
    inject_fake_token(&c, &name);
    c.start_agent(&name).unwrap();
    assert!(is_up(&c.agent_status(&name).unwrap().status));

    c.destroy_agent(&name).unwrap();
    assert_eq!(c.agent_status(&name).unwrap().status, "not_found");
}

#[test]
fn start_nonexistent_fails() {
    assert!(SERVER.client().start_agent("does-not-exist").is_err());
}

#[test]
fn stop_nonexistent_fails() {
    assert!(SERVER.client().stop_agent("does-not-exist").is_err());
}

#[test]
fn create_auto_starts() {
    let c = SERVER.client();
    let st = c.agent_status(&SHARED_RO_AGENT).unwrap();
    assert!(is_up(&st.status), "expected up after create, got {}", st.status);
}

#[test]
fn creation_flow() {
    let c = SERVER.client();
    let agent = TestAgent::create(&c, &unique_agent("flow")).unwrap();

    // A fresh agent has no provider chosen, so it settles at unprovisioned. The
    // authenticated -> alive path needs a real token that survives an upstream call
    // (a fake one is correctly rejected and flipped back), so it's covered by the
    // live tests, not here.
    let status = c.wait_until_running(&agent.name, 180).unwrap();
    assert_eq!(status, "unprovisioned");
}

#[test]
fn start_all_starts_authenticated_agents() {
    let c = SERVER.client();
    let a1 = TestAgent::create(&c, &unique_agent("startall")).unwrap();
    let a2 = TestAgent::create(&c, &unique_agent("startall")).unwrap();
    inject_fake_token(&c, &a1.name);
    inject_fake_token(&c, &a2.name);

    c.start_all().unwrap();

    assert!(is_up(&c.agent_status(&a1.name).unwrap().status));
    assert!(is_up(&c.agent_status(&a2.name).unwrap().status));
}

#[test]
fn start_nonexistent_error_message() {
    let err = SERVER.client().start_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

#[test]
fn destroy_nonexistent_error_message() {
    let err = SERVER.client().destroy_agent("no-such-agent").unwrap_err();
    assert!(err.contains("not found") || err.contains("not_found"), "error should mention not found: {err}");
}

/// vestad owns the lifecycle via Docker's `on-failure:5` restart policy. Assert a freshly created
/// agent's container carries it (recovers crashes, but never auto-starts on daemon boot, so vestad
/// owns boot-start).
#[test]
fn agent_container_uses_on_failure_policy() {
    let client = SERVER.client();
    let agent = TestAgent::create(&client, &unique_agent("policy")).unwrap();
    let container = agent_container_name(&agent.name);

    let name = docker_cmd(&["inspect", "--format", "{{.HostConfig.RestartPolicy.Name}}", &container])
        .expect("inspect restart policy");
    assert_eq!(name, "on-failure", "agent container must use the on-failure restart policy");
    let retries = docker_cmd(&["inspect", "--format", "{{.HostConfig.RestartPolicy.MaximumRetryCount}}", &container])
        .expect("inspect retry count");
    assert_eq!(retries, "5", "on-failure must be capped at 5 retries");
}

/// The headline of vestad-owned lifecycle: desired-run state survives a daemon restart, and boot
/// reconcile starts desired-running agents while leaving user-stopped ones down. Two agents: one
/// left running (user_desired defaults to running), one stopped via the API (user_desired=stopped).
/// Both containers are then taken down (simulating a host reboot — on-failure won't auto-start
/// them), the daemon is restarted reusing the same home, and reconcile must bring up only the
/// desired-running one.
#[test]
fn user_desired_persists_and_boot_start_respects_it() {
    // Keep this server's resources OUT of the orphan-cleanup patterns a concurrent shared-SERVER
    // init scans (a `-t{pid}-` user via unique_user, or a /tmp home), or that cleanup could wipe
    // them mid-test: a home under the cargo target tmpdir and a plain user name.
    let user = format!("lifecycle-e2e-{}", std::process::id());
    let home = tempfile::TempDir::new_in(env!("CARGO_TARGET_TMPDIR")).expect("create persistent home");
    let vestad = find_vestad().expect("locate vestad binary");

    let running_name;
    let stopped_name;
    {
        let server = TestServerBuilder::new()
            .user(&user)
            .home(home.path().to_path_buf())
            .vestad_bin(vestad.clone())
            .start()
            .expect("start vestad");
        let client = server.client();

        running_name = client.create_agent(&unique_agent("desired-run")).expect("create running agent");
        stopped_name = client.create_agent(&unique_agent("desired-stop")).expect("create stopped agent");
        client.wait_until_running(&running_name, 90).expect("running agent should come up");
        client.wait_until_running(&stopped_name, 90).expect("to-stop agent should come up first");

        // User stops one agent -> user_desired=stopped, persisted in settings.json.
        client.stop_agent(&stopped_name).expect("stop agent");
        client.wait_until_stopped(&stopped_name, 60).expect("stopped agent should wind down");

        let settings = read_settings(home.path());
        assert_eq!(
            settings["agents"][&stopped_name]["user_desired"], "stopped",
            "stop must persist user_desired=stopped"
        );

        // Take the running agent's container down WITHOUT touching user_desired (simulates a host
        // reboot: on-failure leaves it down, so vestad must boot-start it). The container name uses
        // THIS server's user (unique_user), not $USER, so build it explicitly.
        docker_cmd(&["stop", &format!("vesta-{user}-{running_name}")]).expect("docker stop running agent");
    }
    // Daemon is now down (server dropped). Restart it on the SAME home so reconcile runs.

    let server = TestServerBuilder::new()
        .user(&user)
        .home(home.path().to_path_buf())
        .vestad_bin(vestad)
        .start()
        .expect("restart vestad on same home");
    let client = server.client();

    // Boot reconcile must START the desired-running agent...
    client.wait_until_running(&running_name, 120).expect("desired-running agent must be boot-started");
    // ...and LEAVE the user-stopped one down. Reconcile is sequential and the running one is up by
    // now, so the stopped one's decision has been made; confirm it stayed down.
    let stopped_state = docker_cmd(&["inspect", "--format", "{{.State.Status}}", &format!("vesta-{user}-{stopped_name}")])
        .expect("inspect stopped agent");
    assert_eq!(stopped_state, "exited", "user-stopped agent must stay down across a daemon restart");

    let _ = client.destroy_agent(&running_name);
    let _ = client.destroy_agent(&stopped_name);
}

/// Read an agent home's settings.json as JSON (panics if missing/invalid — the test created it).
fn read_settings(home: &std::path::Path) -> serde_json::Value {
    let path = home.join(".config/vesta/vestad/settings.json");
    let text = std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).expect("settings.json is valid JSON")
}

