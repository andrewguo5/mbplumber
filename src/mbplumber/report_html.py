"""Self-contained HTML report for the mbPlumber triage output.

Renders a sortable-looking table of triage entries with an expandable
per-node action breakdown. No external assets — all CSS is inlined so the
file opens standalone in any browser.
"""

from __future__ import annotations

import html
from typing import Iterable

from .models import ActionProfile, TriageEntry


def _esc(x: object) -> str:
    return html.escape(str(x))


def _score_class(score: float) -> str:
    if score >= 0.66:
        return "score-high"
    if score >= 0.40:
        return "score-mid"
    return "score-low"


def _fmt_ci(ap: ActionProfile) -> str:
    if ap.ev_ci_low is None or ap.ev_ci_high is None:
        return '<span class="muted">n/a</span>'
    return f"[{ap.ev_ci_low:.0f}, {ap.ev_ci_high:.0f}]"


def _action_rows(profiles: dict[str, ActionProfile]) -> str:
    rows = []
    for ap in sorted(profiles.values(), key=lambda a: a.frequency, reverse=True):
        lc = ' <span class="muted">(low n)</span>' if ap.low_confidence else ""
        ev_cls = "neg" if ap.mean_ev_bb100 < 0 else "pos"
        rows.append(
            "<tr>"
            f"<td>{_esc(ap.action)}</td>"
            f"<td class='num'>{ap.count}</td>"
            f"<td class='num'>{ap.frequency:.0%}</td>"
            f"<td class='num {ev_cls}'>{ap.mean_ev_bb100:.0f}</td>"
            f"<td class='num'>{_fmt_ci(ap)}{lc}</td>"
            "</tr>"
        )
    return (
        "<table class='actions'>"
        "<thead><tr><th>Action</th><th>n</th><th>Freq</th>"
        "<th>EV (BB/100)</th><th>95% CI</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _flag_badges(flags: list[str]) -> str:
    if not flags:
        return ""
    return "".join(f"<span class='flag'>{_esc(f)}</span>" for f in flags)


def render_report(
    entries: Iterable[TriageEntry], stats: dict, title: str = "mbPlumber Triage Report"
) -> str:
    entries = list(entries)
    summary = (
        f"parsed {stats.get('parsed', 0)} hands "
        f"({stats.get('parse_failures', 0)} failures) &middot; "
        f"{stats.get('reached_flop', 0)} reached flop &middot; "
        f"{stats.get('decisions', 0)} decisions &middot; "
        f"{stats.get('nodes', 0)} nodes &middot; "
        f"{stats.get('ranked_entries', 0)} ranked"
    )

    body_rows = []
    for e in entries:
        flagged = " row-flagged" if e.flags else ""
        key = " / ".join(_esc(v) for v in e.node_key.values())
        body_rows.append(
            f"<tr class='node{flagged}'>"
            f"<td class='num rank'>{e.rank}</td>"
            f"<td class='key'>{key}</td>"
            f"<td class='num'>{e.total_hands}</td>"
            f"<td class='num'><span class='score {_score_class(e.composite_score)}'>"
            f"{e.composite_score:.2f}</span></td>"
            f"<td class='flags'>{_flag_badges(e.flags)}</td>"
            f"<td class='hyp'>{_esc(e.hypothesis)}</td>"
            "</tr>"
            f"<tr class='detail'><td></td><td colspan='5'>{_action_rows(e.action_profiles)}</td></tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --line:#262b36; --text:#e6e9ef;
    --muted:#8b93a3; --accent:#5b9dd9;
    --high:#e5484d; --mid:#f5a623; --low:#3fb950;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--text);
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }}
  header {{ padding:24px 28px 12px; }}
  h1 {{ margin:0 0 4px; font-size:20px; }}
  .summary {{ color:var(--muted); font-size:13px; }}
  .legend {{ color:var(--muted); font-size:12px; margin-top:8px; }}
  .legend b {{ color:var(--text); }}
  .wrap {{ padding:8px 28px 48px; }}
  table.main {{ width:100%; border-collapse:collapse; background:var(--panel);
    border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
  table.main > thead th {{
    text-align:left; font-size:11px; letter-spacing:.04em; text-transform:uppercase;
    color:var(--muted); padding:12px 14px; border-bottom:1px solid var(--line); background:#1b1f28;
  }}
  tr.node > td {{ padding:12px 14px; border-bottom:1px solid var(--line); vertical-align:top; }}
  tr.node.row-flagged {{ background:rgba(229,72,77,0.06); }}
  tr.node.row-flagged td.rank {{ box-shadow:inset 3px 0 0 var(--high); }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  td.rank {{ color:var(--muted); }}
  td.key {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; white-space:nowrap; }}
  td.hyp {{ max-width:640px; }}
  .score {{ display:inline-block; min-width:42px; text-align:center; padding:2px 8px;
    border-radius:6px; font-weight:600; font-variant-numeric:tabular-nums; }}
  .score-high {{ background:rgba(229,72,77,0.18); color:#ff7b7f; }}
  .score-mid  {{ background:rgba(245,166,35,0.16); color:#ffc266; }}
  .score-low  {{ background:rgba(63,185,80,0.14); color:#5fd07a; }}
  .flag {{ display:inline-block; background:rgba(229,72,77,0.16); color:#ff8d90;
    border:1px solid rgba(229,72,77,0.35); border-radius:5px; padding:1px 6px;
    font-size:11px; margin:0 4px 4px 0; white-space:nowrap; }}
  tr.detail > td {{ padding:0 14px 14px 14px; border-bottom:1px solid var(--line); }}
  table.actions {{ border-collapse:collapse; width:auto; min-width:420px;
    margin-left:8px; background:#12151c; border:1px solid var(--line); border-radius:8px; }}
  table.actions th, table.actions td {{ padding:6px 12px; border-bottom:1px solid var(--line);
    font-size:12px; }}
  table.actions th {{ color:var(--muted); text-align:left; font-weight:500; }}
  table.actions td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.actions tr:last-child td {{ border-bottom:none; }}
  .num.pos {{ color:#5fd07a; }}
  .num.neg {{ color:#ff7b7f; }}
  .muted {{ color:var(--muted); }}
</style>
</head>
<body>
<header>
  <h1>{_esc(title)}</h1>
  <div class="summary">{summary}</div>
  <div class="legend">
    Each row is a decision node. <b>Flagged</b> rows (red bar) fired a rule-based
    leak heuristic and are the most actionable. The action breakdown below each
    row shows per-action frequency and realized EV — treat large EV figures with
    caution; on small samples they are dominated by variance.
  </div>
</header>
<div class="wrap">
  <table class="main">
    <thead><tr>
      <th>#</th><th>Node (key)</th><th>n</th><th>Score</th><th>Flags</th><th>Hypothesis</th>
    </tr></thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</div>
</body>
</html>
"""
