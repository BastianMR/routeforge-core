//! Help overlay listing the key bindings.

use ratatui::layout::Rect;
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph};
use ratatui::Frame;

pub const BINDINGS: &[(&str, &str)] = &[
    ("1..4", "switch tab"),
    ("tab", "next tab"),
    ("/", "filter (esc clears)"),
    ("?", "toggle this overlay"),
    ("r", "reload skills"),
    ("space", "toggle account enabled"),
    ("d", "disable account"),
    ("up/down", "move selection"),
    ("q, ctrl+c", "quit"),
];

pub fn draw(frame: &mut Frame, area: Rect) {
    let lines: Vec<Line> = BINDINGS
        .iter()
        .map(|(key, action)| {
            Line::from(vec![
                Span::styled(
                    format!("{key:<10}"),
                    Style::default()
                        .fg(Color::Cyan)
                        .add_modifier(Modifier::BOLD),
                ),
                Span::raw(*action),
            ])
        })
        .collect();
    frame.render_widget(
        Paragraph::new(lines).block(Block::default().borders(Borders::ALL).title(" keys ")),
        area,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_documented_action_has_a_binding() {
        for expected in ["1..4", "/", "r", "space", "d", "q, ctrl+c"] {
            assert!(
                BINDINGS.iter().any(|(key, _)| *key == expected),
                "missing binding for {expected}"
            );
        }
    }

    #[test]
    fn the_overlay_advertises_its_own_toggle() {
        assert!(BINDINGS.iter().any(|(key, _)| *key == "?"));
    }

    #[test]
    fn bindings_are_rendered_in_a_stable_order() {
        assert!(BINDINGS.len() >= 9);
        assert_eq!(BINDINGS.first().map(|(k, _)| *k), Some("1..4"));
    }
}
