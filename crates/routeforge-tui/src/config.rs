//! Core URL and client-side settings.

use std::env;
use std::time::Duration;

pub const DEFAULT_URL: &str = "http://127.0.0.1:8787";

/// Base URL of the running core, from `ROUTE_FORGE_URL`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Config {
    pub base_url: String,
    pub tick: Duration,
    pub retry_delay: Duration,
    pub request_timeout: Duration,
    pub max_logs: usize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            base_url: normalize(&env_or("ROUTE_FORGE_URL", DEFAULT_URL)),
            tick: Duration::from_millis(250),
            retry_delay: Duration::from_secs(5),
            request_timeout: Duration::from_secs(10),
            max_logs: 200,
        }
    }
}

impl Config {
    pub fn endpoint(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }
}

fn env_or(name: &str, fallback: &str) -> String {
    env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| fallback.to_string())
}

/// Trim a trailing slash so `endpoint` never doubles up separators.
fn normalize(url: &str) -> String {
    url.trim().trim_end_matches('/').to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_trailing_slash() {
        assert_eq!(normalize("http://host:1/"), "http://host:1");
        assert_eq!(normalize("http://host:1"), "http://host:1");
    }

    #[test]
    fn endpoint_joins_without_double_slash() {
        let config = Config {
            base_url: normalize("http://127.0.0.1:8787/"),
            ..Config::default()
        };
        assert_eq!(
            config.endpoint("/v1/accounts"),
            "http://127.0.0.1:8787/v1/accounts"
        );
    }

    #[test]
    fn default_url_matches_the_core_default_bind() {
        assert_eq!(Config::default().base_url, DEFAULT_URL);
    }

    #[test]
    fn retry_delay_is_five_seconds() {
        assert_eq!(Config::default().retry_delay, Duration::from_secs(5));
    }
}
