use vesta_tests::{TestServerBuilder, unique_user};

pub fn start_pair() -> (vesta_tests::TestServer, vesta_tests::TestServer, String, String) {
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
