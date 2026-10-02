//! Usage tab: a request/error sparkline plus the top-skills list.

use ratatui::layout::{Constraint, Layout, Rect};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span};
use ratatui::widgets::{Block, Borders, Paragraph, Row, Table};
use ratatui::Frame;

use crate::app::App;

pub fn draw(frame: &mut Frame, app: &App, area: Rect) {
    let areas = Layout::vertical([Constraint::Length(9), Constraint::Min(1)]).split(area);

    let samples = series_from(app);
    draw_sparkline(frame, &samples, areas[0]);

    let rows: Vec<Row> = app
        .usage
        .iter()
        .take(20)
        .map(|row| {
            Row::new(vec![
                Span::styled(row.skill_name.clone(), Style::default().fg(Color::Cyan)),
                Span::raw(row.request_count.to_string()),
                Span::styled(
                    row.error_count.to_string(),
                    Style::default().fg(if row.error_count > 0 {
                        Color::Red
                    } else {
                        Color::Green
                    }),
                ),
                Span::raw(format!("{:.0}", row.avg_latency_ms)),
            ])
        })
        .collect();

    let table = Table::new(
        rows,
        [
            Constraint::Min(20),
            Constraint::Length(12),
            Constraint::Length(12),
            Constraint::Length(12),
        ],
    )
    .header(
        Row::new(vec!["skill", "requests", "errors", "avg_ms"])
            .style(Style::default().add_modifier(Modifier::BOLD)),
    )
    .block(
        Block::default()
            .borders(Borders::ALL)
            .title(" top skills (24h) "),
    );
    frame.render_widget(table, areas[1]);
}

/// Reduce the live counters to a small series the sparkline can draw.
pub fn series_from(app: &App) -> Vec<u64> {
    let mut series: Vec<u64> = app
        .usage
        .iter()
        .map(|row| row.request_count.max(0) as u64)
        .collect();
    if series.is_empty() {
        series.push(app.requests_today.max(0) as u64);
    }
    series.truncate(60);
    series
}

/// Text sparkline. Returns an empty string when there is nothing to plot.
pub fn sparkline(values: &[u64]) -> String {
    const BLOCKS: [char; 8] = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█'];
    let peak = values.iter().copied().max().unwrap_or(0);
    if peak == 0 {
        return String::new();
    }
    values
        .iter()
        .map(|value| {
            let index = ((*value as f64 / peak as f64) * 7.0).round() as usize;
            BLOCKS[index.min(BLOCKS.len() - 1)]
        })
        .collect()
}

fn sparkline_block() -> Block<'static> {
    Block::default()
        .borders(Borders::ALL)
        .title(" requests per skill ")
}

fn draw_sparkline(frame: &mut Frame, values: &[u64], area: Rect) {
    frame.render_widget(
        Paragraph::new(Line::from(Span::styled(
            sparkline(values),
            Style::default().fg(Color::Green),
        )))
        .block(sparkline_block()),
        area,
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_series_renders_nothing() {
        assert_eq!(sparkline(&[]), "");
        assert_eq!(sparkline(&[0, 0, 0]), "");
    }

    #[test]
    fn a_single_peak_fills_the_glyph() {
        assert_eq!(sparkline(&[5]), "█");
    }

    #[test]
    fn relative_magnitudes_are_preserved() {
        let rendered = sparkline(&[0, 5]);
        assert_eq!(rendered.chars().count(), 2);
        assert_eq!(rendered.chars().next().unwrap(), '▁');
        assert_eq!(rendered.chars().last().unwrap(), '█');
    }

    #[test]
    fn values_above_the_peak_do_not_panic() {
        assert_eq!(sparkline(&[10, 20, 40]).chars().count(), 3);
    }
}
