use super::common::start_pair;
use vesta_tests::TestAgent;

#[test]
fn two_servers_start_different_ports() {
    let (alice, bob, _, _) = start_pair();

    assert_ne!(alice.port, bob.port, "servers should bind to different ports");

    alice.client().health().expect("alice health check failed");
    bob.client().health().expect("bob health check failed");
}

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
