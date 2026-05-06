use super::common::start_pair;
use vesta_tests::{TestAgent, unique_agent};

#[test]
fn destroy_on_one_doesnt_affect_other() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();
    let name = unique_agent("cross-destroy");

    let alice_agent_name = alice_client.create_agent(&name).unwrap();
    let _bob_agent = TestAgent::create(&bob_client, &name).unwrap();

    alice_client.destroy_agent(&alice_agent_name).unwrap();

    let alice_status = alice_client.agent_status(&name).unwrap();
    assert_eq!(alice_status.status, "not_found", "alice's agent should be gone");

    let bob_status = bob_client.agent_status(&name).unwrap();
    assert_ne!(bob_status.status, "not_found", "bob's agent should still exist");
}

#[test]
fn stop_start_independent() {
    let (alice, bob, _, _) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();
    let name = unique_agent("independence");

    let _alice_agent = TestAgent::create(&alice_client, &name).unwrap();
    let _bob_agent = TestAgent::create(&bob_client, &name).unwrap();

    alice_client.start_agent(&name).unwrap();
    bob_client.start_agent(&name).unwrap();

    let alice_running = alice_client.agent_status(&name).unwrap();
    let bob_running = bob_client.agent_status(&name).unwrap();
    assert_eq!(alice_running.status, "not_authenticated");
    assert_eq!(bob_running.status, "not_authenticated");

    alice_client.stop_agent(&name).unwrap();

    let alice_stopped = alice_client.agent_status(&name).unwrap();
    assert_eq!(alice_stopped.status, "stopped", "alice's agent should be stopped");

    let bob_still_running = bob_client.agent_status(&name).unwrap();
    assert_eq!(bob_still_running.status, "not_authenticated", "bob's agent should still be running");
}
