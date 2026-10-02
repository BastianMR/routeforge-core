//! Terminal rendering. Read-only: every mutation goes through the HTTP API.

pub mod accounts;
pub mod help;
pub mod logs;
pub mod skills;
pub mod usage;

use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph, Tabs};
use ratatui::Frame;

use crate::app::{App, Connection, Tab};

pub fn draw(frame: &mut Frame, app: &App) {
    let areas = Layout::vertical([
        Constraint::Length(3),
        Constraint::Min(1),
        Constraint::Length(3),
    ])
    .split(frame.area());

    draw_tabs(frame, app, areas[0]);
    match app.tab {
        Tab::Accounts => accounts::draw(frame, app, areas[1]),
        Tab::Skills => skills::draw(frame, app, areas[1]),
        Tab::Usage => usage::draw(frame, app, areas[1]),
        Tab::Logs => logs::draw(frame, app, areas[1]),
    }
    draw_footer(frame, app, areas[2]);
    if app.show_help {
        help::draw(frame, help_area(areas[1]));
    }
}

/// Centered key-binding overlay covering the middle of `area`.
fn help_area(area: Rect) -> Rect {
    let width = area.width.saturating_sub(8).min(46).max(20);
    let height = area.height.saturating_sub(6).min(12).max(6);
    Rect {
        x: area.x + area.width.saturating_sub(width) / 2,
        y: area.y + area.height.saturating_sub(height) / 2,
        width,
        height,
    }
}

fn draw_tabs(frame: &mut Frame, app: &App, area: Rect) {
    let titles: Vec<Line> = Tab::ALL
        .iter()
        .enumerate()
        .map(|(i, tab)| Line::from(format!("[{}] {}", i + 1, tab.title())))
        .collect();
    let tabs = Tabs::new(titles)
        .block(Block::default().borders(Borders::ALL).title(" routeforge "))
        .select(match app.tab {
            Tab::Accounts => 0,
            Tab::Skills => 1,
            Tab::Usage => 2,
            Tab::Logs => 3,
        })
        .highlight_style(
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD),
        );
    frame.render_widget(tabs, area);
}

fn draw_footer(frame: &mut Frame, app: &App, area: Rect) {
    let connection = match &app.connection {
        Connection::Connected => Span::styled("live", Style::default().fg(Color::Green)),
        Connection::Connecting => Span::styled("connecting", Style::default().fg(Color::Yellow)),
        Connection::Disconnected(reason) => Span::styled(
            format!("offline: {reason}"),
            Style::default().fg(Color::Red),
        ),
    };
    let filter = if app.filter.is_empty() {
        "/".to_string()
    } else {
        format!("/{}_", app.filter)
    };
    let mut spans = vec![
        Span::raw(format!("{} calls/min ", app.requests_today)),
        Span::raw(format!("{} in cooldown ", app.in_cooldown())),
        Span::raw(format!("{} err/min ", app.errors_per_min)),
        connection,
        Span::raw(format!("  ·  {filter}  ·  q quit")),
    ];
    if let Some(status) = &app.status {
        spans.insert(
            0,
            Span::styled(format!("{status}  "), Style::default().fg(Color::Cyan)),
        );
    }
    let block = Block::default()
        .borders(Borders::ALL)
        .title(if app.filtering { " filter " } else { "" });
    frame.render_widget(Paragraph::new(Line::from(spans)).block(block), area);
}

/// Shared glyph for an account state: green check, yellow dot, red X.
pub fn status_glyph(state: crate::app::StatusKind) -> (&'static str, Color) {
    use crate::app::StatusKind;
    match state {
        StatusKind::Active => ("OK", Color::Green),
        StatusKind::Cooldown => ("..", Color::Yellow),
        StatusKind::Disabled => ("XX", Color::Red),
    }
}

pub fn tags_span(tags: &[String]) -> Span<'static> {
    Span::styled(
        if tags.is_empty() {
            "-".to_string()
        } else {
            tags.join(",")
        },
        Style::default().fg(Color::Magenta),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn help_overlay_is_centered_and_smaller_than_the_body() {
        let body = Rect {
            x: 0,
            y: 0,
            width: 100,
            height: 40,
        };
        let area = help_area(body);
        assert!(area.width < body.width);
        assert!(area.height < body.height);
        assert!(area.x >= body.x);
        assert!(area.y >= body.y);
    }

    #[test]
    fn help_overlay_survives_a_tiny_body() {
        let body = Rect {
            x: 0,
            y: 0,
            width: 4,
            height: 2,
        };
        let area = help_area(body);
        assert_eq!(area.width, 20);
        assert_eq!(area.height, 6);
    }

    #[test]
    fn status_glyphs_use_the_documented_colors() {
        use crate::app::StatusKind;
        assert_eq!(status_glyph(StatusKind::Active).1, Color::Green);
        assert_eq!(status_glyph(StatusKind::Cooldown).1, Color::Yellow);
        assert_eq!(status_glyph(StatusKind::Disabled).1, Color::Red);
    }

    #[test]
    fn empty_tags_render_as_a_dash() {
        assert_eq!(tags_span(&[]).content, "-");
    }

    #[test]
    fn tags_are_joined_with_commas() {
        let tags = vec!["scrape".to_string(), "web".to_string()];
        assert_eq!(tags_span(&tags).content, "scrape,web");
    }
}
