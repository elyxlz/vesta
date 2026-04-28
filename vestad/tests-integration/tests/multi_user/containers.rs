use super::common::start_pair;
use vesta_tests::{TestAgent, unique_agent};

#[test]
fn container_names_include_user() {
    let (alice, bob, alice_user, bob_user) = start_pair();
    let alice_client = alice.client();
    let bob_client = bob.client();
    let name = unique_agent("prefix-test");

    let _alice_agent = TestAgent::create(&alice_client, &name).unwrap();
    let _bob_agent = TestAgent::create(&bob_client, &name).unwrap();

    let output = std::process::Command::new("docker")
        .args(["ps", "-a", "--format", "{{.Names}}"])
        .output()
        .expect("docker ps should work");
    let container_names = String::from_utf8_lossy(&output.stdout);

    let has_alice_container = container_names
        .lines()
        .any(|n| n.contains(alice_user) && n.contains(&name));
    let has_bob_container = container_names
        .lines()
        .any(|n| n.contains(bob_user) && n.contains(&name));

    assert!(has_alice_container, "expected a container with '{alice_user}' and '{name}' in name, got:\n{container_names}");
    assert!(has_bob_container, "expected a container with '{bob_user}' and '{name}' in name, got:\n{container_names}");
}
