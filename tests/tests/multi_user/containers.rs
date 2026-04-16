use super::common::start_pair;
use vesta_tests::TestAgent;

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
