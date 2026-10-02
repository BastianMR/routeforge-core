//! Skills tab: name, source, provider group, account requirement, coverage.

use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::widgets::{Block, Borders, Row, Table};
use ratatui::Frame;

use crate::app::App;

pub fn draw(frame: &mut Frame, app: &App, area: Rect) {
    let rows: Vec<Row> = app
        .visible_skills()
        .iter()
        .map(|skill| {
            Row::new(vec![
                ratatui::text::Span::styled(skill.name.clone(), Style::default().fg(Color::Cyan)),
                ratatui::text::Span::raw(skill.source.clone()),
                ratatui::text::Span::styled(
                    skill.provider_group.clone().unwrap_or_else(|| "-".into()),
                    Style::default().fg(Color::Magenta),
                ),
                ratatui::text::Span::raw(String::from(if skill.requires_account {
                    "yes"
                } else {
                    "no"
                })),
                ratatui::text::Span::raw(app.account_count_for(skill).to_string()),
                ratatui::text::Span::raw(skill.description.clone()),
            ])
        })
        .collect();

    let table = Table::new(
        rows,
        [
            ratatui::layout::Constraint::Length(24),
            ratatui::layout::Constraint::Length(10),
            ratatui::layout::Constraint::Length(16),
            ratatui::layout::Constraint::Length(16),
            ratatui::layout::Constraint::Length(14),
            ratatui::layout::Constraint::Min(10),
        ],
    )
    .header(
        Row::new(vec![
            "name",
            "source",
            "provider_group",
            "requires_account",
            "account_count",
            "description",
        ])
        .style(Style::default().add_modifier(Modifier::BOLD)),
    )
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title(" skills · [r] reload  [/] filter "),
    );
    frame.render_widget(table, area);
}
