//! HTTP and SSE clients for the core.

pub mod client;
pub mod events;

// Only the types referenced as `crate::api::X` are re-exported here; the rest
// are reached through `crate::api::client::X` to keep the module surface honest.
pub use events::BusEvent;
