//! routeforge-tui — a thin, read-mostly terminal client for routeforge-core.
//!
//! The TUI never opens the SQLite database. It reads `GET /v1/accounts`,
//! `/v1/skills`, `/v1/usage`, and `/v1/accounts/pool`, streams
//! `GET /v1/events` for live updates, and performs mutations through
//! `POST /v1/...`.

mod api;
mod app;
mod config;
mod ui;

use anyhow::Result;
use crossterm::event::DisableMouseCapture;
use crossterm::execute;
use crossterm::terminal::{
    disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen,
};
use ratatui::backend::CrosstermBackend;
use ratatui::Terminal;
use tokio::sync::mpsc;

use crate::api::client::Client;
use crate::app::{poll_key, refresh, spawn_event_loop, Action, App, Connection};
use crate::config::Config;

#[tokio::main]
async fn main() -> Result<()> {
    let config = Config::default();
    let client = Client::new(config.clone())?;
    let mut app = App::new(config.clone());

    let (tx, mut rx) = mpsc::channel(512);
    let event_task = spawn_event_loop(config, tx);

    let mut terminal = setup_terminal()?;
    let result = run(&mut terminal, &client, &mut app, &mut rx).await;
    event_task.abort();
    restore_terminal(&mut terminal)?;
    result
}

async fn run(
    terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>,
    client: &Client,
    app: &mut App,
    rx: &mut mpsc::Receiver<api::BusEvent>,
) -> Result<()> {
    let tick = app.config.tick;
    let mut last_refresh = std::time::Instant::now() - app.config.retry_delay;

    loop {
        terminal.draw(|frame| ui::draw(frame, app))?;

        if let Some(key) = poll_key(tick).await {
            let action = app.on_key(key);
            match action {
                Action::Quit => return Ok(()),
                Action::Reload => {
                    app.status = Some("reloading skills...".into());
                    app.status = match client.reload_skills().await {
                        Ok(diff) => Some(format!(
                            "reloaded: +{} -{} ~{}",
                            diff.added.len(),
                            diff.removed.len(),
                            diff.updated.len()
                        )),
                        Err(error) => Some(format!("reload failed: {error}")),
                    };
                    last_refresh = std::time::Instant::now() - app.config.retry_delay;
                }
                Action::ToggleAccount | Action::DisableAccount => {
                    let disable = matches!(action, Action::DisableAccount);
                    match app.selected_account() {
                        Some((id, provider)) => {
                            let outcome = if disable {
                                client.disable_account(id, &provider).await
                            } else {
                                client.toggle_account(id, &provider).await
                            };
                            app.status = match outcome {
                                Ok(()) => Some(format!("{provider}/{id} updated")),
                                Err(error) => Some(format!("{provider}/{id} failed: {error}")),
                            };
                            last_refresh = std::time::Instant::now() - app.config.retry_delay;
                        }
                        None => app.status = Some("no account selected".into()),
                    }
                }
                Action::None => {}
            }
        }

        while let Ok(event) = rx.try_recv() {
            app.apply_event(&event);
        }

        if last_refresh.elapsed() >= app.config.retry_delay {
            last_refresh = std::time::Instant::now();
            match refresh(client).await {
                Ok((accounts, skills, usage, pool)) => {
                    app.accounts = accounts;
                    app.skills = skills;
                    app.usage = usage;
                    app.pool = pool;
                    app.connection = Connection::Connected;
                }
                Err(error) => {
                    app.connection = Connection::Disconnected(error.to_string());
                }
            }
        }
    }
}

fn setup_terminal() -> Result<Terminal<CrosstermBackend<std::io::Stdout>>> {
    enable_raw_mode()?;
    let mut stdout = std::io::stdout();
    execute!(stdout, EnterAlternateScreen, DisableMouseCapture)?;
    Ok(Terminal::new(CrosstermBackend::new(stdout))?)
}

fn restore_terminal(terminal: &mut Terminal<CrosstermBackend<std::io::Stdout>>) -> Result<()> {
    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen)?;
    terminal.show_cursor()?;
    Ok(())
}
