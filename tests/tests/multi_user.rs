use std::collections::HashSet;

use vesta_tests::{TestAgent, TestServerBuilder, unique_user};

fn start_pair() -> (vesta_tests::TestServer, vesta_tests::TestServer, String, String) {
    let alice_user = unique_user("alice");
    let bob_user = unique_user("bob");
    let alice = TestServerBuilder::new()
        .user(&alice_user)
        .start()
        .expect("failed to start alice's server");
    let bob = TestServerBuilder::new()
        .user(&bob_user)
        .start()
        .expect("failed to start bob's server");
    (alice, bob, alice_user, bob_user)
}

// ── Two servers on different ports ────────────────────────────

#[test]
fn two_servers_start_different_ports() {
    let (alice, bob, _, _) = start_pair();

    assert_ne!(alice.port, bob.port, "servers should bind to different ports");

    alice.client().health().expect("alice health check failed");
    bob.client().health().expect("bob health check failed");
}

// ── Agent isolation between users ─────────────────────────────

#[test]
fn agents_isolated_between_users() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();

    let _alice_agent = TestAgent::create(&alice_client, "shared-name").unwrap();
    let _bob_agent = TestAgent::create(&bob_client, "shared-name").unwrap();

    let alice_list = alice_client.list_agents().unwrap();
    let bob_list = bob_client.list_agents().unwrap();

    assert_eq!(alice_list.len(), 1, "alice should see exactly one agent");
    assert_eq!(bob_list.len(), 1, "bob should see exactly one agent");
    assert_eq!(alice_list[0].name, "shared-name");
    assert_eq!(bob_list[0].name, "shared-name");

    let alice_status = alice_client.agent_status("shared-name").unwrap();
    let bob_status = bob_client.agent_status("shared-name").unwrap();
    assert_ne!(alice_status.status, "not_found");
    assert_ne!(bob_status.status, "not_found");
}

// ── Container names include user prefix ───────────────────────

#[test]
fn container_names_include_user() {
    let (alice, bob, alice_user, bob_user) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();

    let _alice_agent = TestAgent::create(&alice_client, "prefix-test").unwrap();
    let _bob_agent = TestAgent::create(&bob_client, "prefix-test").unwrap();

    let output = std::process::Command::new("docker")
        .args(["ps", "-a", "--format", "{{.Names}}"])
        .output()
        .expect("docker ps should work");
    let container_names = String::from_utf8_lossy(&output.stdout);

    let has_alice_container = container_names
        .lines()
        .any(|name| name.contains(&alice_user) && name.contains("prefix-test"));
    let has_bob_container = container_names
        .lines()
        .any(|name| name.contains(&bob_user) && name.contains("prefix-test"));

    assert!(has_alice_container, "expected a container with '{alice_user}' and 'prefix-test' in name, got:\n{container_names}");
    assert!(has_bob_container, "expected a container with '{bob_user}' and 'prefix-test' in name, got:\n{container_names}");
}

// ── Agent WS ports don't collide across users ─────────────────

#[test]
fn agent_ports_dont_collide() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();

    let _alice_a1 = TestAgent::create(&alice_client, "port-test-1").unwrap();
    let _alice_a2 = TestAgent::create(&alice_client, "port-test-2").unwrap();
    let _bob_a1 = TestAgent::create(&bob_client, "port-test-1").unwrap();
    let _bob_a2 = TestAgent::create(&bob_client, "port-test-2").unwrap();

    let alice_agents = alice_client.list_agents().unwrap();
    let bob_agents = bob_client.list_agents().unwrap();

    let mut all_ports: Vec<u16> = alice_agents.iter().map(|a| a.ws_port).collect();
    all_ports.extend(bob_agents.iter().map(|a| a.ws_port));

    let unique_ports: HashSet<u16> = all_ports.iter().copied().collect();
    assert_eq!(
        all_ports.len(),
        unique_ports.len(),
        "all WS ports should be unique across both servers: {all_ports:?}"
    );
}

// ── Destroy on one server doesn't affect the other ────────────

#[test]
fn destroy_on_one_doesnt_affect_other() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();

    let alice_agent_name = alice_client.create_agent("cross-destroy", false).unwrap();
    let _bob_agent = TestAgent::create(&bob_client, "cross-destroy").unwrap();

    alice_client.destroy_agent(&alice_agent_name).unwrap();

    let alice_status = alice_client.agent_status("cross-destroy").unwrap();
    assert_eq!(alice_status.status, "not_found", "alice's agent should be gone");

    let bob_status = bob_client.agent_status("cross-destroy").unwrap();
    assert_ne!(bob_status.status, "not_found", "bob's agent should still exist");
}

// ── Stop on one server doesn't affect the other ───────────────

#[test]
fn stop_start_independent() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();

    let _alice_agent = TestAgent::create(&alice_client, "independence").unwrap();
    let _bob_agent = TestAgent::create(&bob_client, "independence").unwrap();

    alice_client.start_agent("independence").unwrap();
    bob_client.start_agent("independence").unwrap();

    let alice_running = alice_client.agent_status("independence").unwrap();
    let bob_running = bob_client.agent_status("independence").unwrap();
    // Agents are unauthenticated in tests, so combined_status reports "not_authenticated"
    assert_eq!(alice_running.status, "not_authenticated");
    assert_eq!(bob_running.status, "not_authenticated");

    alice_client.stop_agent("independence").unwrap();

    let alice_stopped = alice_client.agent_status("independence").unwrap();
    assert_eq!(alice_stopped.status, "stopped", "alice's agent should be stopped");

    let bob_still_running = bob_client.agent_status("independence").unwrap();
    assert_eq!(bob_still_running.status, "not_authenticated", "bob's agent should still be running");
}
