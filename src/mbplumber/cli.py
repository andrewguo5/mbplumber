"""CLI summary for the mbPlumber triage report (Module 5, minimal).

Usage:
    python -m mbplumber.cli --data ../PokerData/hands --config config/default.yaml --top 25
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .config import load_config, resolve_data_source
from .pipeline import run


def _score_style(score: float) -> str:
    if score >= 0.66:
        return "bold red"
    if score >= 0.4:
        return "yellow"
    return "green"


def _fmt_node_key(node_key: dict[str, str]) -> str:
    return " / ".join(str(v) for v in node_key.values())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mbplumber", description="mbPlumber")
    p.add_argument(
        "--data",
        default=None,
        help="JSONL file or directory of hands. If omitted, falls back to the "
        "MBPLUMBER_DATA env var, then input.data_source in config, then "
        "~/PokerData/hands (mbHUD's default export location).",
    )
    p.add_argument("--config", default=None, help="YAML config (defaults if omitted)")
    p.add_argument("--top", type=int, default=None, help="number of nodes to show")
    p.add_argument("--html", default=None, help="write an HTML triage report to this path")
    p.add_argument(
        "--explorer",
        default=None,
        help="write an HTML decision-node tree explorer to this path",
    )
    p.add_argument(
        "--include-low-sample",
        action="store_true",
        help="include nodes below the low-sample threshold",
    )
    p.add_argument(
        "--dimensions",
        default=None,
        help="comma-separated override of node_dimensions (e.g. street,position,pot_type,action_facing)",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="log adapt/extract warnings")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.verbose else logging.ERROR,
        format="%(levelname)s %(message)s",
    )

    config = load_config(args.config)
    if args.dimensions:
        config.node_dimensions = [d.strip() for d in args.dimensions.split(",") if d.strip()]
    if args.include_low_sample:
        config.triage.include_low_sample = True
    top_n = args.top if args.top is not None else config.output.top_n

    console = Console()
    data_path = resolve_data_source(args.data, config)
    if not data_path.exists():
        console.print(f"[red]data path not found:[/red] {data_path}")
        return 2

    t0 = time.time()
    result = run(data_path, config)
    elapsed = time.time() - t0

    s = result.stats
    console.print(
        f"\n[bold]mbPlumber[/bold]  parsed {s.get('parsed', 0)} hands "
        f"({s.get('parse_failures', 0)} failures), "
        f"{s.get('reached_flop', 0)} reached flop, "
        f"{s.get('decisions', 0)} decisions, "
        f"{s.get('nodes', 0)} nodes, "
        f"{s.get('ranked_entries', 0)} ranked "
        f"— [dim]{elapsed:.1f}s[/dim]\n"
    )

    if args.html:
        from .report_html import render_report

        out = Path(args.html)
        out.write_text(
            render_report(result.triage[:top_n], result.stats), encoding="utf-8"
        )
        console.print(f"[green]HTML report written:[/green] {out.resolve()}\n")

    if args.explorer:
        from .report_explorer import render_explorer

        out = Path(args.explorer)
        out.write_text(
            render_explorer(
                result.decisions, result.nodes, result.triage, config,
                result.stats, result.hands,
            ),
            encoding="utf-8",
        )
        console.print(f"[green]Explorer written:[/green] {out.resolve()}\n")

    table = Table(title=f"Top {top_n} candidate leak nodes", show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Node (key)", overflow="fold")
    table.add_column("n", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Flags", style="magenta")
    table.add_column("Dominant", justify="left")
    table.add_column("Hypothesis", overflow="fold")

    for entry in result.triage[:top_n]:
        dom = max(
            entry.action_profiles.values(),
            key=lambda ap: ap.frequency,
            default=None,
        )
        dom_str = f"{dom.action} {dom.frequency:.0%}" if dom else "-"
        table.add_row(
            str(entry.rank),
            _fmt_node_key(entry.node_key),
            str(entry.total_hands),
            f"[{_score_style(entry.composite_score)}]{entry.composite_score:.2f}[/]",
            ", ".join(entry.flags) if entry.flags else "",
            dom_str,
            entry.hypothesis,
        )

    console.print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
