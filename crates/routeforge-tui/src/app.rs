//! Application state, input handling, and the repaint loop.

use std::collections::VecDeque;

use anyhow::Result;
use chrono::Utc;
use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use serde_json::Value;
use tokio::sync::mpsc;

use crate::api::client::{Account, Client, PoolSnapshot, Skill, UsageRow};
use crate::api::events::BusEvent;
use crate::config::Config;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Accounts,
    Skills,
    Usage,
    Logs,
}

impl Tab {
    pub const ALL: [Tab; 4] = [Tab::Accounts, Tab::Skills, Tab::Usage, Tab::Logs];

    pub fn title(self) -> &'static str {
        match self {
            Tab::Accounts => "Accounts",
            Tab::Skills => "Skills",
            Tab::Usage => "Usage",
            Tab::Logs => "Logs",
        }
    }

    pub fn from_index(index: usize) -> Option<Self> {
        Tab::ALL.get(index).copied()
    }
}

// `Disconnected` carries the reason string, so this cannot be `Copy`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Connection {
    Connected,
    Connecting,
    Disconnected(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StatusKind {
    Active,
    Cooldown,
    Disabled,
}

impl StatusKind {
    pub fn parse(raw: &str) -> Self {
        match raw {
            "cooldown" => StatusKind::Cooldown,
            "disabled" => StatusKind::Disabled,
            _ => StatusKind::Active,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct LogEntry {
    pub id: i64,
    pub kind: String,
    pub summary: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Action {
    None,
    Reload,
    ToggleAccount,
    DisableAccount,
    ToggleHelp,
    Quit,
}

pub struct App {
    pub config: Config,
    pub tab: Tab,
    pub accounts: Vec<Account>,
    pub skills: Vec<Skill>,
    pub usage: Vec<UsageRow>,
    pub pool: PoolSnapshot,
    pub logs: VecDeque<LogEntry>,
    pub connection: Connection,
    pub filter: String,
    pub filtering: bool,
    pub selected: usize,
    pub requests_today: i64,
    pub errors_per_min: i64,
    pub status: Option<String>,
    pub show_help: bool,
}

impl App {
    pub fn new(config: Config) -> Self {
        Self {
            config,
            tab: Tab::Accounts,
            accounts: Vec::new(),
            skills: Vec::new(),
            usage: Vec::new(),
            pool: PoolSnapshot::default(),
            logs: VecDeque::new(),
            connection: Connection::Connecting,
            filter: String::new(),
            filtering: false,
            selected: 0,
            requests_today: 0,
            errors_per_min: 0,
            status: None,
            show_help: false,
        }
    }

    /// `(id, provider)` of the highlighted account, honouring the active filter.
    pub fn selected_account(&self) -> Option<(i64, String)> {
        self.visible_accounts()
            .get(self.selected)
            .map(|a| (a.id, a.provider.clone()))
    }

    pub fn in_cooldown(&self) -> usize {
        self.pool
            .accounts
            .values()
            .filter(|a| a.state == "cooldown")
            .count()
    }

    pub fn state_of(&self, account_id: i64) -> StatusKind {
        match self.pool.accounts.get(&account_id.to_string()) {
            Some(entry) => StatusKind::parse(&entry.state),
            None if self.accounts.iter().any(|a| a.id == account_id) => {
                if self
                    .accounts
                    .iter()
                    .any(|a| a.id == account_id && !a.enabled)
                {
                    StatusKind::Disabled
                } else {
                    StatusKind::Active
                }
            }
            None => StatusKind::Active,
        }
    }

    pub fn account_count_for(&self, skill: &Skill) -> usize {
        match &skill.provider_group {
            Some(group) => self
                .accounts
                .iter()
                .filter(|a| a.tags.iter().any(|t| t == group))
                .count(),
            None => self
                .accounts
                .iter()
                .filter(|a| a.provider == skill.provider)
                .count(),
        }
    }

    pub fn visible_accounts(&self) -> Vec<&Account> {
        if self.filter.is_empty() {
            return self.accounts.iter().collect();
        }
        let needle = self.filter.to_lowercase();
        self.accounts
            .iter()
            .filter(|a| {
                a.label.to_lowercase().contains(&needle)
                    || a.provider.to_lowercase().contains(&needle)
                    || a.tags.iter().any(|t| t.to_lowercase().contains(&needle))
            })
            .collect()
    }

    pub fn visible_skills(&self) -> Vec<&Skill> {
        if self.filter.is_empty() {
            return self.skills.iter().collect();
        }
        let needle = self.filter.to_lowercase();
        self.skills
            .iter()
            .filter(|s| s.name.to_lowercase().contains(&needle))
            .collect()
    }

    /// Apply one keypress. Returns the action the caller must perform.
    pub fn on_key(&mut self, key: KeyEventLike) -> Action {
        if self.filtering {
            match key.code {
                KeyLike::Esc => {
                    self.filtering = false;
                    self.filter.clear();
                }
                KeyLike::Char('c') if key.ctrl => {
                    self.filtering = false;
                    self.filter.clear();
                }
                KeyLike::Char(c) => self.filter.push(c),
                KeyLike::Backspace => {
                    self.filter.pop();
                }
                KeyLike::Enter => self.filtering = false,
                _ => {}
            }
            return Action::None;
        }

        match key.code {
            KeyLike::Char('1') => self.tab = Tab::from_index(0).unwrap_or(self.tab),
            KeyLike::Char('2') => self.tab = Tab::from_index(1).unwrap_or(self.tab),
            KeyLike::Char('3') => self.tab = Tab::from_index(2).unwrap_or(self.tab),
            KeyLike::Char('4') => self.tab = Tab::from_index(3).unwrap_or(self.tab),
            KeyLike::Tab => self.cycle_tab(1),
            KeyLike::BackTab => self.cycle_tab(-1),
            KeyLike::Char('q') => return Action::Quit,
            KeyLike::Char('r') => return Action::Reload,
            KeyLike::Char(' ') => return Action::ToggleAccount,
            KeyLike::Char('d') => return Action::DisableAccount,
            KeyLike::Char('/') => self.filtering = true,
            KeyLike::Char('?') => self.show_help = !self.show_help,
            KeyLike::Char('c') if key.ctrl => return Action::Quit,
            KeyLike::Up => self.selected = self.selected.saturating_sub(1),
            KeyLike::Down => {
                let max = match self.tab {
                    Tab::Accounts => self.visible_accounts().len(),
                    Tab::Skills => self.visible_skills().len(),
                    _ => 0,
                };
                if max > 0 && self.selected + 1 < max {
                    self.selected += 1;
                }
            }
            _ => {}
        }
        Action::None
    }

    fn cycle_tab(&mut self, delta: isize) {
        let count = Tab::ALL.len() as isize;
        let index = (self.tab as isize + delta).rem_euclid(count) as usize;
        self.tab = Tab::from_index(index).unwrap_or(self.tab);
    }

    /// Fold one SSE event into the in-memory state.
    pub fn apply_event(&mut self, event: &BusEvent) {
        self.push_log(event);
        match event.kind.as_str() {
            "account.cooldown_started" => {
                self.set_pool_state(&event.data, "cooldown");
            }
            "account.recovered" => {
                self.set_pool_state(&event.data, "active");
            }
            "account.disabled" => {
                self.set_pool_state(&event.data, "disabled");
                if let Some(id) = event.data["account_id"].as_i64() {
                    if let Some(account) = self.accounts.iter_mut().find(|a| a.id == id) {
                        account.enabled = false;
                    }
                }
            }
            "usage.tick" => {
                self.errors_per_min = event.data["errors"].as_i64().unwrap_or(0);
                self.requests_today = event.data["requests"].as_i64().unwrap_or(0);
            }
            "skill.reloaded" => {
                self.status = Some(format!(
                    "skills reloaded: +{} -{} ~{}",
                    count_array(&event.data["added"]),
                    count_array(&event.data["removed"]),
                    count_array(&event.data["updated"]),
                ));
            }
            _ => {}
        }
    }

    fn set_pool_state(&mut self, data: &Value, state: &str) {
        let Some(id) = data["account_id"].as_i64() else {
            return;
        };
        let key = id.to_string();
        let entry =
            self.pool
                .accounts
                .entry(key)
                .or_insert_with(|| crate::api::client::PoolAccount {
                    account_id: id,
                    ..Default::default()
                });
        entry.account_id = id;
        entry.state = state.to_string();
    }

    fn push_log(&mut self, event: &BusEvent) {
        let summary = summarize(&event.kind, &event.data);
        self.logs.push_front(LogEntry {
            id: event.id,
            kind: event.kind.clone(),
            summary,
        });
        while self.logs.len() > self.config.max_logs {
            self.logs.pop_back();
        }
    }
}

fn count_array(value: &Value) -> usize {
    value.as_array().map_or(0, |a| a.len())
}

fn summarize(kind: &str, data: &Value) -> String {
    let stamp = Utc::now().format("%H:%M:%S");
    match kind {
        "account.cooldown_started" => format!(
            "{stamp} cooldown #{} for {}s",
            data["account_id"], data["until"]
        ),
        "account.recovered" => format!("{stamp} recovered #{}", data["account_id"]),
        "account.disabled" => format!("{stamp} disabled #{}", data["account_id"]),
        "call.completed" => format!(
            "{stamp} {} {} {}ms",
            data["skill"], data["status"], data["latency_ms"]
        ),
        "usage.tick" => format!(
            "{stamp} tick {} req / {} err",
            data["requests"], data["errors"]
        ),
        "skill.reloaded" => format!("{stamp} skills reloaded"),
        other => format!("{stamp} {other}"),
    }
}

/// Small abstraction so key handling is unit-testable without crossterm.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyLike {
    Char(char),
    Enter,
    Esc,
    Backspace,
    Tab,
    BackTab,
    Up,
    Down,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KeyEventLike {
    pub code: KeyLike,
    pub ctrl: bool,
}

impl From<Event> for KeyEventLike {
    fn from(event: Event) -> Self {
        match event {
            Event::Key(key) if key.kind != KeyEventKind::Release => Self {
                code: match key.code {
                    KeyCode::Char(c) => KeyLike::Char(c),
                    KeyCode::Enter => KeyLike::Enter,
                    KeyCode::Esc => KeyLike::Esc,
                    KeyCode::Backspace => KeyLike::Backspace,
                    KeyCode::Tab => KeyLike::Tab,
                    KeyCode::BackTab => KeyLike::BackTab,
                    KeyCode::Up => KeyLike::Up,
                    KeyCode::Down => KeyLike::Down,
                    _ => KeyLike::Char('\0'),
                },
                ctrl: key.modifiers.contains(event::KeyModifiers::CONTROL),
            },
            _ => Self {
                code: KeyLike::Char('\0'),
                ctrl: false,
            },
        }
    }
}

/// Poll for one keypress, waiting at most `timeout`.
///
/// `crossterm::event::poll` blocks, so it runs on the blocking pool: calling it
/// directly would stall a tokio worker for the whole tick and delay the SSE
/// events queued on `rx`.
pub async fn poll_key(timeout: std::time::Duration) -> Option<KeyEventLike> {
    tokio::task::spawn_blocking(move || {
        if event::poll(timeout).unwrap_or(false) {
            match event::read() {
                Ok(event) => Some(KeyEventLike::from(event)),
                Err(_) => None,
            }
        } else {
            None
        }
    })
    .await
    .unwrap_or(None)
}

/// Refresh the read-only data from the core.
pub async fn refresh(
    client: &Client,
) -> Result<(Vec<Account>, Vec<Skill>, Vec<UsageRow>, PoolSnapshot)> {
    let accounts = client.accounts().await?;
    let skills = client.skills().await?;
    let usage = client.usage("skill", "24h").await.unwrap_or_default();
    let pool = client.pool().await.unwrap_or_default();
    Ok((accounts, skills, usage, pool))
}

/// Spawn the SSE consumer, reconnecting every `retry_delay` after the stream ends.
pub fn spawn_event_loop(config: Config, tx: mpsc::Sender<BusEvent>) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut last_id = 0;
        loop {
            // `run` returns on a clean close or on error. Either way the core may
            // be restarting, so resume from the last id actually forwarded.
            match crate::api::events::run(config.clone(), tx.clone(), last_id).await {
                Ok(seen) => last_id = seen,
                Err(_) => {}
            }
            if tx.is_closed() {
                return;
            }
            tokio::time::sleep(config.retry_delay).await;
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn app() -> App {
        App::new(Config::default())
    }

    fn key(code: KeyLike) -> KeyEventLike {
        KeyEventLike { code, ctrl: false }
    }

    #[test]
    fn number_keys_switch_tabs() {
        let mut app = app();
        app.on_key(key(KeyLike::Char('3')));
        assert_eq!(app.tab, Tab::Usage);
        app.on_key(key(KeyLike::Char('1')));
        assert_eq!(app.tab, Tab::Accounts);
    }

    #[test]
    fn tab_cycles_and_wraps() {
        let mut app = app();
        app.on_key(key(KeyLike::Tab));
        assert_eq!(app.tab, Tab::Skills);
        app.on_key(key(KeyLike::BackTab));
        assert_eq!(app.tab, Tab::Accounts);
        app.on_key(key(KeyLike::BackTab));
        assert_eq!(app.tab, Tab::Logs);
    }

    #[test]
    fn q_and_ctrl_c_quit() {
        let mut app = app();
        assert_eq!(app.on_key(key(KeyLike::Char('q'))), Action::Quit);
        assert_eq!(
            app.on_key(KeyEventLike {
                code: KeyLike::Char('c'),
                ctrl: true
            }),
            Action::Quit
        );
    }

    #[test]
    fn r_space_and_d_map_to_actions() {
        let mut app = app();
        assert_eq!(app.on_key(key(KeyLike::Char('r'))), Action::Reload);
        assert_eq!(app.on_key(key(KeyLike::Char(' '))), Action::ToggleAccount);
        assert_eq!(app.on_key(key(KeyLike::Char('d'))), Action::DisableAccount);
    }

    #[test]
    fn question_mark_toggles_the_help_overlay() {
        let mut app = app();
        assert!(!app.show_help);
        assert_eq!(app.on_key(key(KeyLike::Char('?'))), Action::None);
        assert!(app.show_help);
        app.on_key(key(KeyLike::Char('?')));
        assert!(!app.show_help);
    }

    #[test]
    fn selected_account_follows_the_cursor() {
        let mut app = app();
        app.accounts = vec![
            Account {
                id: 1,
                provider: "firecrawl".into(),
                ..Default::default()
            },
            Account {
                id: 2,
                provider: "tavily".into(),
                ..Default::default()
            },
        ];
        assert_eq!(app.selected_account(), Some((1, "firecrawl".into())));
        app.on_key(key(KeyLike::Down));
        assert_eq!(app.selected_account(), Some((2, "tavily".into())));
    }

    #[test]
    fn selected_account_respects_the_filter() {
        let mut app = app();
        app.accounts = vec![
            Account {
                id: 1,
                provider: "firecrawl".into(),
                ..Default::default()
            },
            Account {
                id: 2,
                provider: "tavily".into(),
                ..Default::default()
            },
        ];
        app.filter = "tavily".into();
        assert_eq!(app.selected_account(), Some((2, "tavily".into())));
    }

    #[test]
    fn selected_account_is_none_when_the_list_is_empty() {
        assert_eq!(app().selected_account(), None);
    }

    #[test]
    fn slash_enters_filter_mode_and_typing_is_captured() {
        let mut app = app();
        app.on_key(key(KeyLike::Char('/')));
        assert!(app.filtering);
        app.on_key(key(KeyLike::Char('f')));
        app.on_key(key(KeyLike::Char('c')));
        assert_eq!(app.filter, "fc");
        app.on_key(key(KeyLike::Enter));
        assert!(!app.filtering);
        assert_eq!(app.filter, "fc");
    }

    #[test]
    fn escape_clears_the_filter() {
        let mut app = app();
        app.on_key(key(KeyLike::Char('/')));
        app.on_key(key(KeyLike::Char('x')));
        app.on_key(key(KeyLike::Esc));
        assert_eq!(app.filter, "");
        assert!(!app.filtering);
    }

    #[test]
    fn backspace_edits_the_filter() {
        let mut app = app();
        app.filtering = true;
        app.on_key(key(KeyLike::Char('a')));
        app.on_key(key(KeyLike::Char('b')));
        app.on_key(key(KeyLike::Backspace));
        assert_eq!(app.filter, "a");
    }

    #[test]
    fn selection_moves_down_and_is_clamped() {
        let mut app = app();
        app.accounts = vec![
            Account {
                id: 1,
                ..Default::default()
            },
            Account {
                id: 2,
                ..Default::default()
            },
        ];
        app.on_key(key(KeyLike::Down));
        assert_eq!(app.selected, 1);
        app.on_key(key(KeyLike::Down));
        assert_eq!(app.selected, 1);
        app.on_key(key(KeyLike::Up));
        assert_eq!(app.selected, 0);
    }

    #[test]
    fn selection_never_goes_below_zero() {
        let mut app = app();
        app.on_key(key(KeyLike::Up));
        assert_eq!(app.selected, 0);
    }

    #[test]
    fn cooldown_event_updates_the_account_row_without_a_fetch() {
        let mut app = app();
        app.accounts = vec![Account {
            id: 5,
            ..Default::default()
        }];
        let event = BusEvent {
            id: 1,
            kind: "account.cooldown_started".into(),
            data: serde_json::json!({"account_id": 5, "until": "t", "reason": "429"}),
        };
        app.apply_event(&event);
        assert_eq!(app.state_of(5), StatusKind::Cooldown);
    }

    #[test]
    fn recovered_event_returns_the_account_to_active() {
        let mut app = app();
        app.accounts = vec![Account {
            id: 5,
            ..Default::default()
        }];
        app.apply_event(&BusEvent {
            id: 1,
            kind: "account.cooldown_started".into(),
            data: serde_json::json!({"account_id": 5}),
        });
        app.apply_event(&BusEvent {
            id: 2,
            kind: "account.recovered".into(),
            data: serde_json::json!({"account_id": 5}),
        });
        assert_eq!(app.state_of(5), StatusKind::Active);
    }

    #[test]
    fn disabled_event_clears_the_account_enabled_flag() {
        let mut app = app();
        app.accounts = vec![Account {
            id: 7,
            enabled: true,
            ..Default::default()
        }];
        app.apply_event(&BusEvent {
            id: 1,
            kind: "account.disabled".into(),
            data: serde_json::json!({"account_id": 7}),
        });
        assert!(!app.accounts[0].enabled);
        assert_eq!(app.state_of(7), StatusKind::Disabled);
    }

    #[test]
    fn usage_tick_updates_the_footer_counters() {
        let mut app = app();
        app.apply_event(&BusEvent {
            id: 1,
            kind: "usage.tick".into(),
            data: serde_json::json!({"window": "1m", "requests": 124, "errors": 3}),
        });
        assert_eq!(app.requests_today, 124);
        assert_eq!(app.errors_per_min, 3);
    }

    #[test]
    fn skill_reloaded_event_records_the_diff_counts() {
        let mut app = app();
        app.apply_event(&BusEvent {
            id: 1,
            kind: "skill.reloaded".into(),
            data: serde_json::json!({"added": ["a"], "removed": [], "updated": ["b", "c"]}),
        });
        assert_eq!(app.status.as_deref(), Some("skills reloaded: +1 -0 ~2"));
    }

    #[test]
    fn logs_are_capped_and_newest_first() {
        let mut config = Config::default();
        config.max_logs = 3;
        let mut app = App::new(config);
        for id in 1..=5 {
            app.apply_event(&BusEvent {
                id,
                kind: "call.completed".into(),
                data: serde_json::json!({"skill": "echo"}),
            });
        }
        assert_eq!(app.logs.len(), 3);
        assert_eq!(app.logs[0].id, 5);
    }

    #[test]
    fn account_count_honors_provider_group_tags() {
        let mut app = app();
        app.accounts = vec![
            Account {
                id: 1,
                provider: "firecrawl",
                tags: vec!["scrape".into()],
                ..Default::default()
            },
            Account {
                id: 2,
                provider: "tavily",
                tags: vec!["scrape".into()],
                ..Default::default()
            },
            Account {
                id: 3,
                provider: "exa",
                tags: vec!["search".into()],
                ..Default::default()
            },
        ];
        let grouped = Skill {
            name: "web/scrape".into(),
            provider: "ignored".into(),
            provider_group: Some("scrape".into()),
            ..Default::default()
        };
        assert_eq!(app.account_count_for(&grouped), 2);

        let by_provider = Skill {
            name: "exa/search".into(),
            provider: "exa".into(),
            provider_group: None,
            ..Default::default()
        };
        assert_eq!(app.account_count_for(&by_provider), 1);
    }

    #[test]
    fn filter_matches_label_provider_and_tags() {
        let mut app = app();
        app.accounts = vec![
            Account {
                id: 1,
                provider: "firecrawl",
                label: "fc1",
                tags: vec!["scrape".into()],
                ..Default::default()
            },
            Account {
                id: 2,
                provider: "tavily",
                label: "tv1",
                tags: vec![],
                ..Default::default()
            },
        ];
        app.filter = "crawl".into();
        assert_eq!(app.visible_accounts().len(), 1);
        app.filter = "scrape".into();
        assert_eq!(app.visible_accounts().len(), 1);
        app.filter = "tv1".into();
        assert_eq!(app.visible_accounts().len(), 1);
        app.filter = "zzz".into();
        assert!(app.visible_accounts().is_empty());
    }

    #[test]
    fn in_cooldown_counts_only_cooling_accounts() {
        let mut app = app();
        app.pool = PoolSnapshot::default();
        app.pool.accounts.insert(
            "1".into(),
            crate::api::client::PoolAccount {
                account_id: 1,
                state: "cooldown".into(),
                ..Default::default()
            },
        );
        app.pool.accounts.insert(
            "2".into(),
            crate::api::client::PoolAccount {
                account_id: 2,
                state: "active".into(),
                ..Default::default()
            },
        );
        assert_eq!(app.in_cooldown(), 1);
    }

    #[test]
    fn status_kind_parses_unknown_as_active() {
        assert_eq!(StatusKind::parse("cooldown"), StatusKind::Cooldown);
        assert_eq!(StatusKind::parse("disabled"), StatusKind::Disabled);
        assert_eq!(StatusKind::parse("whatever"), StatusKind::Active);
    }

    #[test]
    fn summarize_never_leaks_an_api_key_field() {
        let summary = summarize(
            "call.completed",
            &serde_json::json!({"skill": "echo", "status": "success", "latency_ms": 5}),
        );
        assert!(summary.contains("echo"));
        assert!(!summary.contains("api_key"));
    }
}
