use std::collections::HashSet;

use super::common::start_pair;
use vesta_tests::TestAgent;

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
