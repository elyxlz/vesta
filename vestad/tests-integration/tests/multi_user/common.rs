use std::sync::LazyLock;

use vesta_tests::{TestServer, TestServerBuilder, unique_user};

/// Two long-lived `vestad serve` processes (one per simulated user) shared
/// across every multi_user test. Booting fresh pairs per-test was the bulk of
/// the multi_user suite's wall-clock cost; tests already use distinct agent
/// names, so a single pair is enough to exercise cross-user isolation.
/// Cleanup of these vestads happens at the next run via `kill_orphan_vestads`.
pub static SHARED_PAIR: LazyLock<SharedPair> = LazyLock::new(|| {
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
    SharedPair { alice, bob, alice_user, bob_user }
});

pub struct SharedPair {
    pub alice: TestServer,
    pub bob: TestServer,
    pub alice_user: String,
    pub bob_user: String,
}

pub fn start_pair() -> (&'static TestServer, &'static TestServer, &'static str, &'static str) {
    (
        &SHARED_PAIR.alice,
        &SHARED_PAIR.bob,
        &SHARED_PAIR.alice_user,
        &SHARED_PAIR.bob_user,
    )
}
