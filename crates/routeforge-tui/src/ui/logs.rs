//! Logs tab: the most recent events, newest first.

use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::Line;
use ratatui::widgets::{Block, Borders, Paragraph};
use ratatui::Frame;

use crate::app::{App, LogEntry};

pub fn draw(frame: &mut Frame, app: &App, area: Rect) {
    let lines: Vec<Line> = app.logs.iter().map(render_line).collect();
    let title = format!(" events ({} kept) ", app.logs.len());
    frame.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::ALL).title(title)),
        area,
    );
}

fn render_line(entry: &LogEntry) -> Line<'static> {
    Line::from(vec![
        ratatui::text::Span::styled(
            format!("{:<24}", entry.kind),
            Style::default()
                .fg(color_for(&entry.kind))
                .add_modifier(Modifier::BOLD),
        ),
        ratatui::text::Span::raw(entry.summary.clone()),
    ])
}

pub fn color_for(kind: &str) -> Color {
    match kind {
        "account.cooldown_started" | "account.disabled" => Color::Yellow,
        "account.recovered" => Color::Green,
        "call.completed" => Color::Cyan,
        "usage.tick" => Color::Blue,
        "skill.reloaded" => Color::Magenta,
        _ => Color::Gray,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cooldown_and_disabled_are_yellow() {
        assert_eq!(color_for("account.cooldown_started"), Color::Yellow);
        assert_eq!(color_for("account.disabled"), Color::Yellow);
    }

    #[test]
    fn recovery_is_green() {
        assert_eq!(color_for("account.recovered"), Color::Green);
    }

    #[test]
    fn unknown_events_fall_back_to_gray() {
        assert_eq!(color_for("something.new"), Color::Gray);
    }
}
