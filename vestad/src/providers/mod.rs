//! Per-provider HTTP handlers (Claude OAuth, OpenRouter API, ...).
//!
//! Each submodule owns the handlers for one provider, registered under
//! `/providers/{id}/...` in serve.rs. Adding a new provider means dropping a
//! new submodule here, plugging it into the agent's provider.py logic, and
//! teaching the wizard's ChoiceStep about it.

pub mod claude;
pub mod openrouter;
