//! SSE consumer for `GET /v1/events`.

use anyhow::{Context, Result};
use eventsource_stream::Eventsource;
use futures_util::StreamExt;
use serde_json::Value;
use tokio::sync::mpsc;

use crate::config::Config;

#[derive(Debug, Clone, PartialEq)]
pub struct BusEvent {
    pub id: i64,
    pub kind: String,
    pub data: Value,
}

/// Parse one SSE frame into a `BusEvent`, or `None` for keepalive comments.
pub fn parse_frame(id: i64, event: &str, data: &str) -> Option<BusEvent> {
    if data.trim().is_empty() {
        return None;
    }
    let parsed = serde_json::from_str::<Value>(data).ok()?;
    Some(BusEvent {
        id,
        kind: event.trim().to_string(),
        data: parsed,
    })
}

/// Consume the SSE stream until it ends, forwarding events to `tx`.
///
/// Returns the id of the last event forwarded so the caller can resume from
/// there on the next connection instead of replaying the whole ring buffer.
/// Reconnecting is the caller's job, so it can sleep between attempts.
pub async fn run(
    config: Config,
    tx: mpsc::Sender<BusEvent>,
    mut last_event_id: i64,
) -> Result<i64> {
    let response = reqwest::Client::new()
        .get(config.endpoint("/v1/events"))
        .header("Last-Event-ID", last_event_id.to_string())
        .send()
        .await
        .context("GET /v1/events")?;
    if !response.status().is_success() {
        anyhow::bail!("/v1/events returned {}", response.status());
    }

    let mut stream = response.bytes_stream().eventsource();
    while let Some(message) = stream.next().await {
        let message = match message {
            Ok(message) => message,
            Err(_) => break,
        };
        // eventsource-stream exposes `event` as a plain String, defaulting to
        // "message" when the frame carries no `event:` field.
        let kind = if message.event.trim().is_empty() {
            "message".to_string()
        } else {
            message.event.clone()
        };
        let Some(event) = parse_frame(last_event_id + 1, &kind, &message.data) else {
            continue; // keepalive comment
        };
        last_event_id = event.id;
        if tx.send(event).await.is_err() {
            break; // UI went away
        }
    }
    Ok(last_event_id)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_cooldown_frame() {
        let event = parse_frame(
            42,
            "account.cooldown_started",
            r#"{"account_id":5,"until":"2026-09-25T12:34:56Z","reason":"429"}"#,
        )
        .expect("frame parses");
        assert_eq!(event.id, 42);
        assert_eq!(event.kind, "account.cooldown_started");
        assert_eq!(event.data["account_id"], 5);
        assert_eq!(event.data["reason"], "429");
    }

    #[test]
    fn ignores_keepalive_comments() {
        assert!(parse_frame(1, "", "").is_none());
        assert!(parse_frame(1, "keepalive", "   ").is_none());
    }

    #[test]
    fn ignores_malformed_json() {
        assert!(parse_frame(1, "call.completed", "not json").is_none());
    }

    #[test]
    fn defaults_an_absent_event_name() {
        let event = parse_frame(7, "  ", r#"{"skill":"echo"}"#).expect("frame parses");
        assert_eq!(event.kind, "");
    }
}
