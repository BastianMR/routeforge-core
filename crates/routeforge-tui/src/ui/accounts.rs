//! Accounts tab: label, provider, tags, status, last used.

use ratatui::layout::Rect;
use ratatui::style::{Color, Style};
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, Cell, Row, Table};
use ratatui::Frame;

use crate::app::App;
use crate::ui::{status_glyph, tags_span};

pub fn draw(frame: &mut Frame, app: &App, area: Rect) {
    let rows: Vec<Row> = app
        .visible_accounts()
        .iter()
        .enumerate()
        .map(|(index, account)| {
            let state = app.state_of(account.id);
            let (glyph, color) = status_glyph(state);
            let mut label = ratatui::text::Span::styled(
                account.label.clone(),
                Style::default().fg(Color::Cyan),
            );
            if index == app.selected {
                label = ratatui::text::Span::styled(
                    format!("> {}", account.label),
                    Style::default()
                        .fg(Color::Cyan)
                        .add_modifier(ratatui::style::Modifier::BOLD),
                );
            }
            let mut status = Line::from(vec![
                ratatui::text::Span::styled(format!("{glyph} "), Style::default().fg(color)),
                ratatui::text::Span::raw(state_word(state, app, account.id)),
            ]);
            if state == crate::app::StatusKind::Cooldown {
                if let Some(entry) = app.pool.accounts.get(&account.id.to_string()) {
                    status.push_span(ratatui::text::Span::styled(
                        format!(" {:.0}s", entry.cooldown_remaining_seconds),
                        Style::default().fg(Color::Yellow),
                    ));
                }
            }
            // `Cell::from` is the common currency: `Span` and `Line` both
            // convert into it, and a bare `vec!` would force them to one type.
            Row::new(vec![
                Cell::from(label),
                Cell::from(account.provider.clone()),
                Cell::from(tags_span(&account.tags)),
                Cell::from(status),
                Cell::from(account.last_used_at.clone().unwrap_or_else(|| "-".into())),
            ])
        })
        .collect();

    let table = Table::new(
        rows,
        [
            ratatui::layout::Constraint::Length(20),
            ratatui::layout::Constraint::Length(14),
            ratatui::layout::Constraint::Length(22),
            ratatui::layout::Constraint::Length(16),
            ratatui::layout::Constraint::Min(10),
        ],
    )
    .header(
        Row::new(vec!["label", "provider", "tags", "status", "last_used"])
            .style(Style::default().add_modifier(ratatui::style::Modifier::BOLD)),
    )
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title(" accounts · [space] toggle  [d] disable  [/] filter "),
    );
    frame.render_widget(table, area);
}

fn state_word(state: crate::app::StatusKind, app: &App, account_id: i64) -> String {
    match state {
        crate::app::StatusKind::Cooldown => "cooldown".into(),
        crate::app::StatusKind::Disabled => "disabled".into(),
        crate::app::StatusKind::Active => {
            let enabled = app
                .accounts
                .iter()
                .find(|a| a.id == account_id)
                .map(|a| a.enabled)
                .unwrap_or(true);
            if enabled {
                "active".into()
            } else {
                "disabled".into()
            }
        }
    }
}
