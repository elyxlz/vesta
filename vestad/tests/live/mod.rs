// cargo builds the vestad binary for this integration-test crate and exposes its path via
// the compile-time CARGO_BIN_EXE_vestad. Hand it to the shared harness (which prefers
// VESTAD_BIN) before the LazyLock TestServer initializes, so we never run a stale binary.
#[ctor::ctor(unsafe)]
fn _point_harness_at_built_vestad() {
    std::env::set_var("VESTAD_BIN", env!("CARGO_BIN_EXE_vestad"));
}

mod common;
mod dreamer;
mod file_ops;
mod interrupt;
mod mcp_tools;