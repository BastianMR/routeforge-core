//! Typed HTTP client. The TUI never touches SQLite; every mutation is a POST.

use anyhow::{Context, Result};
use serde::Deserialize;

use crate::config::Config;

#[derive(Debug, Clone, Deserialize, PartialEq, Eq, Default)]
pub struct Account {
    pub id: i64,
    pub provider: String,
    pub label: String,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default = "default_true")]
    pub enabled: bool,
    pub last_used_at: Option<String>,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq, Default)]
pub struct Skill {
    pub name: String,
    #[serde(default)]
    pub source: String,
    pub provider: String,
    #[serde(default)]
    pub provider_group: Option<String>,
    #[serde(default = "default_true")]
    pub requires_account: bool,
    pub description: String,
}

#[derive(Debug, Clone, Deserialize, PartialEq)]
pub struct UsageRow {
    pub skill_name: String,
    #[serde(default)]
    pub account_id: Option<i64>,
    #[serde(default)]
    pub request_count: i64,
    #[serde(default)]
    pub error_count: i64,
    #[serde(default)]
    pub avg_latency_ms: f64,
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq, Default)]
pub struct ReloadDiff {
    #[serde(default)]
    pub added: Vec<String>,
    #[serde(default)]
    pub removed: Vec<String>,
    #[serde(default)]
    pub updated: Vec<String>,
}

/// Pool state keyed by account id, from `GET /v1/accounts/pool`.
#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct PoolSnapshot {
    #[serde(default)]
    pub accounts: std::collections::BTreeMap<String, PoolAccount>,
}

// `cooldown_remaining_seconds` is an f64, so this cannot be `Eq`.
#[derive(Debug, Clone, Deserialize, PartialEq, Default)]
pub struct PoolAccount {
    pub account_id: i64,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub cooldown_remaining_seconds: f64,
    #[serde(default)]
    pub consecutive_failures: i64,
}

#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    config: Config,
}

impl Client {
    pub fn new(config: Config) -> Result<Self> {
        let http = reqwest::Client::builder()
            .timeout(config.request_timeout)
            .build()
            .context("building the HTTP client")?;
        Ok(Self { http, config })
    }

    pub fn config(&self) -> &Config {
        &self.config
    }

    pub async fn accounts(&self) -> Result<Vec<Account>> {
        let body: serde_json::Value = self.get("/v1/accounts").await?;
        // The endpoint groups by provider; flatten into one list.
        let mut out: Vec<Account> = Vec::new();
        if let Some(map) = body.as_object() {
            for accounts in map.values() {
                if let Some(items) = accounts.as_array() {
                    for item in items {
                        out.push(serde_json::from_value(item.clone())?);
                    }
                }
            }
        }
        out.sort_by_key(|a| a.id);
        Ok(out)
    }

    pub async fn skills(&self) -> Result<Vec<Skill>> {
        self.get("/v1/skills").await
    }

    pub async fn usage(&self, group_by: &str, since: &str) -> Result<Vec<UsageRow>> {
        self.get(&format!("/v1/usage?group_by={group_by}&since={since}"))
            .await
    }

    pub async fn pool(&self) -> Result<PoolSnapshot> {
        self.get("/v1/accounts/pool").await
    }

    pub async fn reload_skills(&self) -> Result<ReloadDiff> {
        let response = self
            .http
            .post(self.config.endpoint("/v1/skills/manage/reload"))
            .send()
            .await
            .context("POST /v1/skills/manage/reload")?;
        Ok(response.json().await?)
    }

    pub async fn toggle_account(&self, account_id: i64, provider: &str) -> Result<()> {
        self.post_account("/v1/accounts/manage/toggle", account_id, provider)
            .await
    }

    pub async fn disable_account(&self, account_id: i64, provider: &str) -> Result<()> {
        self.post_account("/v1/accounts/manage/disable", account_id, provider)
            .await
    }

    async fn post_account(&self, path: &str, account_id: i64, provider: &str) -> Result<()> {
        let response = self
            .http
            .post(self.config.endpoint(path))
            .json(&serde_json::json!({"account_id": account_id, "provider": provider}))
            .send()
            .await
            .with_context(|| format!("POST {path}"))?;
        if !response.status().is_success() {
            anyhow::bail!("{path} returned {}", response.status());
        }
        Ok(())
    }

    async fn get<T: serde::de::DeserializeOwned>(&self, path: &str) -> Result<T> {
        let response = self
            .http
            .get(self.config.endpoint(path))
            .send()
            .await
            .with_context(|| format!("GET {path}"))?;
        if !response.status().is_success() {
            anyhow::bail!("GET {path} returned {}", response.status());
        }
        Ok(response.json().await?)
    }
}

const fn default_true() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn account_defaults_to_enabled_without_the_field() {
        let account: Account =
            serde_json::from_str(r#"{"id":1,"provider":"p","label":"l"}"#).expect("parses");
        assert!(account.enabled);
        assert!(account.tags.is_empty());
    }

    #[test]
    fn skill_requires_account_defaults_to_true() {
        let skill: Skill = serde_json::from_str(
            r#"{"name":"s","provider":"p","description":"d","source":"builtin"}"#,
        )
        .expect("parses");
        assert!(skill.requires_account);
        assert_eq!(skill.provider_group, None);
    }

    #[test]
    fn usage_row_tolerates_missing_aggregates() {
        let row: UsageRow = serde_json::from_str(r#"{"skill_name":"echo"}"#).expect("parses");
        assert_eq!(row.request_count, 0);
        assert_eq!(row.avg_latency_ms, 0.0);
    }

    #[test]
    fn reload_diff_tolerates_empty_lists() {
        let diff: ReloadDiff = serde_json::from_str("{}").expect("parses");
        assert!(diff.added.is_empty());
    }

    #[test]
    fn pool_snapshot_reads_the_account_map() {
        let snapshot: PoolSnapshot = serde_json::from_str(
            r#"{"accounts":{"5":{"account_id":5,"label":"fc","state":"cooldown","cooldown_remaining_seconds":30.0,"consecutive_failures":1}}}"#,
        )
        .expect("parses");
        let account = snapshot.accounts.get("5").expect("account 5");
        assert_eq!(account.state, "cooldown");
        assert_eq!(account.consecutive_failures, 1);
    }
}
