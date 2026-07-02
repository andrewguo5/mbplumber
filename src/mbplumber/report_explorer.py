"""Self-contained HTML decision-node EXPLORER.

A two-pane page: a collapsible decision TREE on the left (branches follow the
ordered node dimensions, mirroring the game tree), and a detail pane on the
right that, for the selected leaf, shows the per-action EV breakdown and the
individual hero decisions behind it (which hands took which action — the
hand-selection view that realized-EV divergence alone can't give you).

All data is embedded as JSON; navigation is vanilla JS. No external assets.
"""

from __future__ import annotations

import html
import json

from .config import Config
from .explorer import build_tree
from .models import Decision, Hand, NodeProfile, TriageEntry


def _esc(x: object) -> str:
    return html.escape(str(x))


def render_explorer(
    decisions: list[Decision],
    nodes: list[NodeProfile],
    triage: list[TriageEntry],
    config: Config,
    stats: dict,
    hands: dict[str, Hand] | None = None,
    title: str = "mbPlumber Decision-Node Explorer",
) -> str:
    tree = build_tree(decisions, nodes, triage, config, hands)
    # Embedded safely: </script> can't appear in JSON, but escape '<' to be safe.
    data_json = json.dumps(tree).replace("<", "\\u003c")

    summary = (
        f"{stats.get('decisions', 0)} decisions &middot; "
        f"{stats.get('nodes', 0)} nodes &middot; "
        f"path: {' › '.join(_esc(d) for d in tree['dimensions'])}"
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --panel2:#12151c; --line:#262b36;
    --text:#e6e9ef; --muted:#8b93a3; --accent:#5b9dd9;
    --high:#e5484d; --pos:#5fd07a; --neg:#ff7b7f;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ height:100%; margin:0; }}
  body {{
    background:var(--bg); color:var(--text); display:flex; flex-direction:column;
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }}
  header {{ padding:16px 24px 12px; border-bottom:1px solid var(--line); }}
  h1 {{ margin:0 0 4px; font-size:18px; }}
  .summary {{ color:var(--muted); font-size:12px; }}
  .layout {{ display:flex; flex:1; min-height:0; }}
  .tree {{
    width:42%; max-width:560px; overflow:auto; padding:12px 8px 40px;
    border-right:1px solid var(--line); background:var(--panel2);
  }}
  .detail {{ flex:1; overflow:auto; padding:16px 24px 48px; }}
  ul.tree-list {{ list-style:none; margin:0; padding-left:14px; }}
  ul.tree-list.root {{ padding-left:0; }}
  li.tnode {{ margin:1px 0; }}
  .twrap {{ display:flex; align-items:center; gap:6px; border-radius:6px;
    padding:2px 6px; cursor:pointer; white-space:nowrap; }}
  .twrap:hover {{ background:rgba(91,157,217,0.10); }}
  .twrap.selected {{ background:rgba(91,157,217,0.20); }}
  .twrap.leaf .caret {{ visibility:hidden; }}
  .caret {{ width:12px; color:var(--muted); font-size:11px; user-select:none; }}
  .tlabel {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:13px; }}
  .tdim {{ color:var(--muted); font-size:11px; }}
  .tcount {{ color:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; margin-left:4px; }}
  .tev {{ font-size:11px; font-variant-numeric:tabular-nums; margin-left:6px;
    padding:0 5px; border-radius:4px; }}
  .tev.pos {{ color:var(--pos); background:rgba(95,208,122,0.10); }}
  .tev.neg {{ color:var(--neg); background:rgba(255,123,127,0.10); }}
  .tflag {{ width:6px; height:6px; border-radius:50%; background:var(--high); display:inline-block; }}
  li.collapsed > ul.tree-list {{ display:none; }}
  .crumbs {{ font-family:ui-monospace,Menlo,monospace; font-size:13px; color:var(--accent); margin-bottom:6px; }}
  .meta {{ color:var(--muted); font-size:12px; margin-bottom:14px; }}
  .flag {{ display:inline-block; background:rgba(229,72,77,0.16); color:#ff8d90;
    border:1px solid rgba(229,72,77,0.35); border-radius:5px; padding:1px 6px;
    font-size:11px; margin:0 4px 4px 0; }}
  h3 {{ font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
    margin:18px 0 8px; }}
  table {{ border-collapse:collapse; background:var(--panel); border:1px solid var(--line);
    border-radius:8px; overflow:hidden; }}
  th,td {{ padding:6px 12px; border-bottom:1px solid var(--line); font-size:12px; text-align:left; }}
  th {{ color:var(--muted); font-weight:500; background:#1b1f28; }}
  td.num,th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  tr:last-child td {{ border-bottom:none; }}
  .pos {{ color:var(--pos); }} .neg {{ color:var(--neg); }} .muted {{ color:var(--muted); }}
  tr.act {{ cursor:pointer; }}
  tr.act:hover td {{ background:rgba(91,157,217,0.08); }}
  tr.act.open td {{ background:rgba(91,157,217,0.12); }}
  tr.hands td {{ padding:0; }}
  tr.hands table {{ width:100%; border:none; border-radius:0; background:var(--panel2); }}
  /* Lock the detail-pane table geometry so expanding a hand doesn't reflow
     the parent tables: fixed layout makes column widths depend on the header
     (and colgroup), not on the expanded content. */
  table#acts {{ width:100%; max-width:680px; table-layout:fixed; }}
  table#acts th:first-child, table#acts td:first-child {{ width:34%; }}
  table.hlist {{ table-layout:fixed; }}
  table.hlist td {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  /* All-in (last col) is left-aligned next to the right-aligned EV column —
     pad it left so "yes" isn't crowding the EV number. */
  table.hlist th:last-child, table.hlist td:last-child {{ padding-left:24px; }}
  .placeholder {{ color:var(--muted); margin-top:40px; text-align:center; }}
  .ev {{ font-variant-numeric:tabular-nums; }}
  .pill {{ display:inline-block; padding:1px 7px; border-radius:5px; font-size:11px;
    background:#1b1f28; color:var(--muted); margin-left:6px; }}
  /* Per-hand expandable detail (action log + cards). */
  tr.hrow.has-detail {{ cursor:pointer; }}
  tr.hrow.has-detail:hover td {{ background:rgba(91,157,217,0.08); }}
  tr.hrow.open td {{ background:rgba(91,157,217,0.12); }}
  .hcaret {{ color:var(--muted); user-select:none; }}
  tr.hdetail > td {{ padding:10px 14px; background:#0d1016; }}
  .card {{ display:inline-block; min-width:24px; text-align:center; padding:1px 5px;
    margin:0 2px; border-radius:4px; background:#23272f; color:#e6e9ef;
    font-family:ui-monospace,Menlo,monospace; font-size:12px; }}
  .card.red {{ color:#ff8d90; }}
  .hdmeta {{ margin-bottom:10px; font-size:12px; display:flex; flex-wrap:wrap;
    align-items:center; gap:6px; }}
  .hdlabel {{ color:var(--muted); text-transform:uppercase; letter-spacing:.04em;
    font-size:10px; margin-left:8px; }}
  table.alog {{ width:100%; table-layout:fixed; }}
  table.alog th, table.alog td {{ padding:4px 8px; overflow:hidden;
    text-overflow:ellipsis; }}
  /* Street + Action are short labels — keep them narrow; give the two numeric
     columns (Amount, Pot before) the room they need to never clip a number. */
  table.alog th:nth-child(1), table.alog td:nth-child(1) {{ width:10%; }}
  table.alog th:nth-child(2), table.alog td:nth-child(2) {{ width:28%; }}
  table.alog th:nth-child(3), table.alog td:nth-child(3) {{ width:18%; }}
  table.alog th:nth-child(4), table.alog td:nth-child(4) {{ width:20%; }}
  table.alog th:nth-child(5), table.alog td:nth-child(5) {{ width:24%; }}
  table.alog td.num {{ overflow:visible; padding-right:10px; }}
  table.alog tr.herorow td {{ background:rgba(91,157,217,0.10); }}
  table.alog tr.outcome td {{ background:#1b1f28; border-top:2px solid var(--line);
    font-weight:500; }}
  .herowin {{ color:var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>{_esc(title)}</h1>
  <div class="summary">{summary}</div>
</header>
<div class="layout">
  <div class="tree" id="tree"></div>
  <div class="detail" id="detail">
    <div class="placeholder">Select a leaf node in the tree to inspect the
    decisions made there and their realized EVs.</div>
  </div>
</div>
<script>
const DATA = {data_json};
const DIMS = DATA.dimensions;
const HANDS = DATA.hands || {{}};

const fmtEv = v => (v>=0?"+":"") + v.toFixed(0);
const fmtEv1 = v => (v>=0?"+":"") + v.toFixed(1);
const fmtPct = v => (v*100).toFixed(0) + "%";
function esc(s){{ return String(s).replace(/[&<>"]/g, c => (
  {{"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}}[c])); }}

// Render a list of card strings (e.g. ["Ah","Kd"]) as colored card pills.
const SUIT = {{h:"♥",d:"♦",c:"♣",s:"♠"}};
const REDSUIT = {{h:1,d:1}};
function cards(list){{
  if (!list || !list.length) return '<span class="muted">—</span>';
  return list.map(c => {{
    const r = c.slice(0,-1), s = c.slice(-1).toLowerCase();
    const red = REDSUIT[s] ? ' red' : '';
    return '<span class="card'+red+'">'+esc(r)+(SUIT[s]||esc(s))+'</span>';
  }}).join('');
}}

// Build the expandable per-hand detail: cards, board, net, full action log.
function handDetail(handId){{
  const h = HANDS[handId];
  if (!h) return '<div class="muted">No detail available for this hand.</div>';
  let out = '<div class="hdmeta">' +
    '<span class="hdlabel">Hero</span> ' + cards(h.hero_hole_cards) +
    ' <span class="hdlabel">Board</span> ' + cards(h.board) +
    ' <span class="hdlabel">Pot type</span> ' + esc(h.pot_type) +
    ' <span class="hdlabel">Hand net</span> <span class="ev '+
      (h.hero_net_bb<0?'neg':'pos')+'">'+fmtEv1(h.hero_net_bb)+' BB</span>' +
    ' <span class="hdlabel">Result</span> '+(h.hero_won?'won':'lost')+'</div>';
  // Action log grouped by street, with the pot before each action.
  out += '<table class="alog"><thead><tr><th>Street</th><th>Player</th>' +
    '<th>Action</th><th class="num">Amount<br>(BB)</th>' +
    '<th class="num">Pot before<br>(BB)</th></tr></thead><tbody>';
  let lastStreet = null;
  for (const a of h.actions){{
    if (a.is_post) continue;  // blinds/antes — not decisions; pot_before reflects them
    const newStreet = a.street !== lastStreet;
    lastStreet = a.street;
    const cls = a.is_hero ? ' class="herorow"' : '';
    out += '<tr'+cls+'><td>'+(newStreet?esc(a.street):'')+'</td>' +
      '<td>'+esc(a.player)+(a.is_hero?' <span class="pill">hero</span>':'')+'</td>' +
      '<td>'+esc(a.action)+(a.all_in?' <span class="pill">all-in</span>':'')+'</td>' +
      '<td class="num">'+(a.amount_bb?a.amount_bb.toFixed(2):'–')+'</td>' +
      '<td class="num">'+a.pot_before_bb.toFixed(2)+'</td></tr>';
  }}
  // Outcome row: who took down the pot (confirms the result by eye).
  const winners = h.pot_winners || {{}};
  const names = Object.keys(winners);
  let outcome;
  if (!names.length){{
    outcome = '<span class="muted">no pot awarded (uncontested return)</span>';
  }} else {{
    outcome = names.map(n => {{
      const isHero = n === h.hero;
      return '<span'+(isHero?' class="herowin"':'')+'>'+esc(n) +
        (isHero?' <span class="pill">hero</span>':'') +
        ' takes ' + fmtEv1(winners[n]) + ' BB</span>';
    }}).join(' &middot; ');
  }}
  out += '<tr class="outcome"><td>Result</td><td colspan="4">' +
    (names.length>1 ? '<span class="hdlabel">split pot</span> ' : '') +
    outcome + '</td></tr>';
  out += '</tbody></table>';
  return out;
}}

function renderTree(node, parentEl, depth){{
  const ul = document.createElement("ul");
  ul.className = "tree-list" + (depth===0 ? " root" : "");
  for (const child of node.children) ul.appendChild(renderNode(child, depth));
  parentEl.appendChild(ul);
}}

function renderNode(node, depth){{
  const li = document.createElement("li");
  li.className = "tnode";
  const isLeaf = node.children.length === 0 && node.leaf;
  const hasFlags = isLeaf && node.leaf.flags && node.leaf.flags.length;

  const wrap = document.createElement("div");
  wrap.className = "twrap" + (isLeaf ? " leaf" : "");
  const evCls = node.mean_ev_bb < 0 ? "neg" : "pos";
  wrap.innerHTML =
    '<span class="caret">' + (isLeaf ? "" : "▸") + '</span>' +
    '<span class="tlabel">' + esc(node.label) + '</span>' +
    '<span class="tdim">' + esc(node.dimension || "") + '</span>' +
    '<span class="tcount">n=' + node.count + '</span>' +
    '<span class="tev ' + evCls + '" title="aggregate mean realized EV (BB) over all ' +
      node.count + ' decisions in this subtree">' + fmtEv1(node.mean_ev_bb) + ' BB</span>' +
    (hasFlags ? ' <span class="tflag" title="flagged"></span>' : '');

  if (isLeaf){{
    wrap.addEventListener("click", () => selectLeaf(node, wrap));
  }} else {{
    li.classList.add("collapsed");
    wrap.addEventListener("click", () => {{
      li.classList.toggle("collapsed");
      const c = wrap.querySelector(".caret");
      c.textContent = li.classList.contains("collapsed") ? "▸" : "▾";
    }});
  }}
  li.appendChild(wrap);
  if (!isLeaf) renderTree(node, li, depth+1);
  return li;
}}

let selectedEl = null;
function selectLeaf(node, wrap){{
  if (selectedEl) selectedEl.classList.remove("selected");
  wrap.classList.add("selected");
  selectedEl = wrap;
  renderDetail(node.leaf);
}}

function renderDetail(leaf){{
  const d = document.getElementById("detail");
  const crumbs = DIMS.map(k => esc(leaf.node_key[k])).join(" › ");
  let html = '<div class="crumbs">' + crumbs + '</div>';

  const flags = (leaf.flags||[]).map(f => '<span class="flag">'+esc(f)+'</span>').join("");
  const score = leaf.composite_score!=null
    ? 'score ' + leaf.composite_score.toFixed(2) +
      ' (A '+ (leaf.score_a??0).toFixed(2) +' / B '+ (leaf.score_b??0).toFixed(2) +')'
    : 'not ranked';
  html += '<div class="meta">' + leaf.total_hands + ' hands' +
    (leaf.low_sample ? ' <span class="pill">low sample</span>' : '') +
    ' &middot; ' + score + (flags ? '<br>'+flags : '') +
    (leaf.hypothesis ? '<br><span class="muted">'+esc(leaf.hypothesis)+'</span>' : '') +
    '</div>';

  // Per-action breakdown.
  html += '<h3>Actions at this node</h3>';
  const profs = (leaf.action_profiles||[]).slice().sort((a,b)=>b.frequency-a.frequency);
  // group decisions by action for the drill-down.
  const byAction = {{}};
  for (const r of leaf.decisions) (byAction[r.action] = byAction[r.action]||[]).push(r);

  html += '<table id="acts"><thead><tr><th>Action</th><th class="num">n</th>' +
    '<th class="num">Freq</th><th class="num">Mean EV<br>(BB)</th>' +
    '<th class="num">95% CI (BB)</th></tr></thead><tbody>';
  for (const p of profs){{
    // Profiles store EV in BB/100; show in BB.
    const meanBb = p.mean_ev_bb100 / 100;
    const ci = (p.ev_ci_low!=null && p.ev_ci_high!=null)
      ? '['+(p.ev_ci_low/100).toFixed(1)+', '+(p.ev_ci_high/100).toFixed(1)+']'
      : '<span class="muted">n/a</span>';
    const lc = p.low_confidence ? ' <span class="muted">(low n)</span>' : '';
    const cls = meanBb<0 ? 'neg' : 'pos';
    html += '<tr class="act" data-action="'+esc(p.action)+'">' +
      '<td><span class="acaret">▸ </span>'+esc(p.action)+'</td>' +
      '<td class="num">'+p.count+'</td>' +
      '<td class="num">'+fmtPct(p.frequency)+'</td>' +
      '<td class="num ev '+cls+'">'+fmtEv1(meanBb)+'</td>' +
      '<td class="num">'+ci+lc+'</td></tr>';
    // hidden drill-down row with the individual hands; each hand row is itself
    // expandable into the full action log so the EV can be reconciled by eye.
    const rows = (byAction[p.action]||[]).slice().sort((a,b)=>a.ev_bb-b.ev_bb);
    let hs = '<table class="hlist">' +
      '<colgroup><col style="width:55%"><col style="width:15%">' +
      '<col style="width:15%"><col style="width:15%"></colgroup>' +
      '<thead><tr><th>Hand</th><th class="num">Sizing</th>' +
      '<th class="num">EV (BB)</th><th>All-in</th></tr></thead><tbody>';
    for (const r of rows){{
      const cls2 = r.ev_bb<0 ? 'neg' : 'pos';
      const expandable = !!HANDS[r.hand_id];
      hs += '<tr class="hrow'+(expandable?' has-detail':'')+'" data-hand="'+esc(r.hand_id)+'">' +
        '<td><span class="hcaret">'+(expandable?'▸ ':'')+'</span>'+esc(r.hand_id)+'</td>' +
        '<td class="num">'+(r.sizing_pct!=null ? r.sizing_pct.toFixed(0)+'%' : '–')+'</td>' +
        '<td class="num ev '+cls2+'">'+r.ev_bb.toFixed(1)+'</td>' +
        '<td>'+(r.all_in ? 'yes' : '')+'</td></tr>';
      if (expandable){{
        hs += '<tr class="hdetail" data-detail="'+esc(r.hand_id)+'" style="display:none">' +
          '<td colspan="4">'+handDetail(r.hand_id)+'</td></tr>';
      }}
    }}
    hs += '</tbody></table>';
    html += '<tr class="hands" data-for="'+esc(p.action)+'" style="display:none"><td colspan="5">'+hs+'</td></tr>';
  }}
  html += '</tbody></table>';
  html += '<div class="meta" style="margin-top:10px">Click an action row to see the ' +
    'individual hands you took it with — compare which hands went to which ' +
    'action before trusting an EV gap (it may be hand selection, not a leak).</div>';

  d.innerHTML = html;
  d.querySelectorAll('tr.act').forEach(tr => {{
    tr.addEventListener('click', () => {{
      const a = tr.getAttribute('data-action');
      const hrow = d.querySelector('tr.hands[data-for="'+CSS.escape(a)+'"]');
      const open = hrow.style.display !== 'none';
      hrow.style.display = open ? 'none' : '';
      tr.classList.toggle('open', !open);
      tr.querySelector('td .acaret').textContent =
        (open ? '▸ ' : '▾ ');
    }});
  }});
  // Expand an individual hand into its full action log. The detail row is the
  // immediate sibling, so toggle by sibling (a hand_id may repeat across
  // streets within one node, making data-detail non-unique).
  d.querySelectorAll('tr.hrow.has-detail').forEach(tr => {{
    tr.addEventListener('click', () => {{
      const drow = tr.nextElementSibling;
      if (!drow || !drow.classList.contains('hdetail')) return;
      const open = drow.style.display !== 'none';
      drow.style.display = open ? 'none' : '';
      tr.classList.toggle('open', !open);
      tr.querySelector('td .hcaret').textContent = (open ? '▸ ' : '▾ ');
    }});
  }});
}}

renderTree(DATA.root, document.getElementById("tree"), 0);
</script>
</body>
</html>
"""
