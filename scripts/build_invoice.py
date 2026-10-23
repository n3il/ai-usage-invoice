#!/usr/bin/env python3
"""Render an invoice + work log page from collect.py's usage.json.

Usage:
  build_invoice.py --usage DIR/usage.json --out DIR/invoice.html --rate 150 --client "Client Name"
     [--project-name "site.com"] [--from-name "Studio"] [--from-detail "email · address"] [--client-detail "..."]
     [--invoice-number INV-2026-001] [--issue-date YYYY-MM-DD] [--due-days 14] [--currency USD]
     [--basis billable|floor] [--round 0.25] [--title "..."] [--notes "..."] [--no-prompt-log] [--no-invoice]
"""
import argparse, collections, datetime as dt, html, json, math
from zoneinfo import ZoneInfo

ap = argparse.ArgumentParser()
ap.add_argument('--usage', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--rate', type=float, default=0); ap.add_argument('--currency', default='USD')
ap.add_argument('--client', default=''); ap.add_argument('--client-detail', default='')
ap.add_argument('--from-name', default=''); ap.add_argument('--from-detail', default='')
ap.add_argument('--project-name', default=''); ap.add_argument('--title', default='')
ap.add_argument('--invoice-number', default=''); ap.add_argument('--issue-date', default='')
ap.add_argument('--due-days', type=int, default=14)
ap.add_argument('--basis', choices=['billable', 'floor'], default='billable')
ap.add_argument('--round', type=float, default=0, help='round each day up to this many hours (e.g. 0.25)')
ap.add_argument('--notes', default='')
ap.add_argument('--no-prompt-log', action='store_true'); ap.add_argument('--no-invoice', action='store_true')
a = ap.parse_args()
d = json.load(open(a.usage))
TZ = ZoneInfo(d['tz'])
E = html.escape
P = lambda s: dt.datetime.fromisoformat(s)
def hm(s): s = int(round(s)); return f"{s // 3600}h {s % 3600 // 60:02d}m"
def M(n): return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(n)
def money(x): return f"{x:,.2f} {a.currency}" if a.currency not in ('USD', 'EUR', 'GBP', 'CHF') else {'USD': '$', 'EUR': '€', 'GBP': '£', 'CHF': 'CHF '}[a.currency] + f"{x:,.2f}"
def chips(ts): return ' '.join(f'<span class="chip {"claude" if t.startswith("Claude") else "codex"}">{E(t)}</span>' for t in ts)
def t12(s): return P(s).strftime('%-I:%M %p')
proj = a.project_name or d['project'].rstrip('/').split('/')[-1]
title = a.title or f"{proj} Invoice" if not a.no_invoice else (a.title or f"{proj} AI Work Log")
first, last = P(d['range']['first']), P(d['range']['last'])
period = f"{first.strftime('%b %-d')} – {last.strftime('%b %-d, %Y')}"
sessions = d['sessions']; tools = list(d['tools'].keys())

# ---- invoice lines: one per day ----
days = collections.OrderedDict()
for s in sessions:
    k = P(s['start']).date()
    x = days.setdefault(k, dict(billable=0, n=0, sessions=0, agent=0))
    x['billable'] += s['billable']; x['n'] += s['n']; x['sessions'] += 1; x['agent'] += s['agent_wall']
scale = 1.0 if a.basis == 'billable' else (d['floor'] / d['billable'] if d['billable'] else 0)
lines = []
for k, x in days.items():
    h = x['billable'] * scale / 3600
    if a.round: h = math.ceil(h / a.round - 1e-9) * a.round
    h = round(h, 2)
    lines.append((k, x, h, round(h * a.rate, 2)))
hours = round(sum(l[2] for l in lines), 2); total = round(sum(l[3] for l in lines), 2)
issue = dt.date.fromisoformat(a.issue_date) if a.issue_date else dt.date.today()
due = issue + dt.timedelta(days=a.due_days)
inv_no = a.invoice_number or f"INV-{issue.strftime('%Y%m%d')}"

# ---- charts ----
L, W, ROW = 128, 640, 34
def nice(mx, n=4):
    raw = mx / n; mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    return step, step * math.ceil(mx / step) if mx else step
def bar(x, y, w, h, cls):
    if w <= 0.5: return ''
    r = min(4, w, h / 2)
    return f'<path class="{cls}" d="M{x:.1f},{y} H{x + w - r:.1f} Q{x + w:.1f},{y} {x + w:.1f},{y + r} V{y + h - r} Q{x + w:.1f},{y + h} {x + w - r:.1f},{y + h} H{x:.1f} Z"/>'
def lab(s): return P(s['start']).strftime('%b %-d · %-I:%M %p')
def axis(step, mx, fmt, H):
    g, v = '', 0.0
    while v <= mx + 1e-9:
        x = L + (W - L - 44) * v / mx
        g += f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{H}"/><text x="{x:.1f}" y="{H + 14}" text-anchor="middle">{fmt(v)}</text>'
        v += step
    return g
def chart_time():
    step, mx = nice(max(max(s['billable'], s['agent_wall']) for s in sessions) / 60); H = ROW * len(sessions); sc = (W - L - 44) / (mx * 60)
    g = axis(step, mx, lambda v: f"{v:g}m", H)
    for i, s in enumerate(sessions):
        y = i * ROW
        tip = f"{lab(s)}<br>Your time: {hm(s['billable'])}<br>Agent runtime: {hm(s['agent_wall'])}<br>{s['n']} prompts"
        g += f'<rect class="hit" x="0" y="{y}" width="{W}" height="{ROW}" data-tip="{E(tip)}"/><text class="lab" x="0" y="{y + ROW / 2 + 4}">{lab(s)}</text>'
        g += bar(L, y + 6, s['billable'] * sc, 10, 'k-you') + bar(L, y + 18, s['agent_wall'] * sc, 10, 'k-agent')
        g += f'<text x="{L + s["billable"] * sc + 5:.1f}" y="{y + 15}">{round(s["billable"] / 60)}m</text><text x="{L + s["agent_wall"] * sc + 5:.1f}" y="{y + 27}">{round(s["agent_wall"] / 60)}m</text>'
    return f'<svg viewBox="0 0 {W} {H + 20}" role="img" aria-label="Your time and agent runtime per work session">{g}</svg>'
def chart_tokens():
    step, mx = nice(max(sum(s['tokens'].values()) for s in sessions) / 1e6); H = ROW * len(sessions); sc = (W - L - 44) / (mx * 1e6)
    g = axis(step, mx, lambda v: f"{v:g}M", H)
    for i, s in enumerate(sessions):
        y = i * ROW; x = L
        tip = lab(s) + ''.join(f"<br>{t}: {M(s['tokens'].get(t, 0))}" for t in tools)
        g += f'<rect class="hit" x="0" y="{y}" width="{W}" height="{ROW}" data-tip="{E(tip)}"/><text class="lab" x="0" y="{y + ROW / 2 + 4}">{lab(s)}</text>'
        segs = [(t, s['tokens'].get(t, 0) * sc) for t in tools if s['tokens'].get(t, 0)]
        for j, (t, w) in enumerate(segs):
            cls = 'k-claude' if t.startswith('Claude') else 'k-codex'
            if j < len(segs) - 1: g += f'<rect class="{cls}" x="{x:.1f}" y="{y + 9}" width="{max(w - 2, 0):.1f}" height="16"/>'
            else: g += bar(x, y + 9, w, 16, cls)
            x += w
        g += f'<text x="{x + 5:.1f}" y="{y + 21}">{M(sum(s["tokens"].values()))}</text>'
    return f'<svg viewBox="0 0 {W} {H + 20}" role="img" aria-label="Tokens per work session by tool">{g}</svg>'

# ---- sections ----
inv = '' if a.no_invoice else f"""
<section class="invoice">
  <div class="inv-head">
    <div><span class="eyebrow">Invoice</span><h1>{E(inv_no)}</h1></div>
    <dl><dt>Issued</dt><dd>{issue.strftime('%b %-d, %Y')}</dd><dt>Due</dt><dd>{due.strftime('%b %-d, %Y')}</dd><dt>Period</dt><dd>{period}</dd></dl>
  </div>
  <div class="parties">
    <div><span class="eyebrow">From</span><b>{E(a.from_name)}</b><span class="muted">{E(a.from_detail)}</span></div>
    <div><span class="eyebrow">Bill to</span><b>{E(a.client)}</b><span class="muted">{E(a.client_detail)}</span></div>
  </div>
  <div class="scroll"><table class="lines"><thead><tr><th>Description</th><th class="r">Hours</th><th class="r">Rate</th><th class="r">Amount</th></tr></thead><tbody>
  {''.join(f"<tr><td><b>{k.strftime('%a %b %-d')}</b> · AI-assisted development, {E(proj)}<br><span class='muted'>{x['sessions']} work session{'s' if x['sessions'] != 1 else ''}, {x['n']} prompts</span></td><td class='n r'>{h:.2f}</td><td class='n r'>{money(a.rate)}</td><td class='n r'>{money(amt)}</td></tr>" for k, x, h, amt in lines)}
  </tbody><tfoot><tr><td>Total</td><td class="n r">{hours:.2f}</td><td></td><td class="n r total">{money(total)}</td></tr></tfoot></table></div>
  {f'<p class="muted">{E(a.notes)}</p>' if a.notes else ''}
  <p class="muted">Hours are estimated from timestamped prompt logs; the method and full log follow below.{' Each day is rounded up to the nearest ' + f'{a.round:g} h.' if a.round else ''}{' Billed at the floor estimate (writing prompts and reading answers only).' if a.basis == 'floor' else ''}</p>
</section>"""

sens_rows = ''.join(f"<tr{' class=rec' if s['idle'] == d['idle'] else ''}><td>{s['idle']:g} min</td><td class=n>{s['sessions']}</td><td class=n>{hm(s['span'])}</td><td class=n>{hm(s['lead'])}</td><td class=n>{hm(s['tail'])} ({s['capped']})</td><td class=n><b>{hm(s['billable'])}</b></td></tr>" for s in d['sensitivity'])
sess_rows = ''.join(f"<tr><td>{P(s['start']).strftime('%b %-d')}</td><td class=n>{t12(s['start'])} – {t12(s['last'])}</td><td>{chips(s['tools'])}</td><td class=n>{s['n']}</td><td class=n>{M(sum(s['tokens'].values()))}</td><td class=n>{hm(s['agent_wall'])}</td><td class=n>{hm(s['lead'])}</td><td class=n>{hm(s['tail'])}</td><td class=n><b>{hm(s['billable'])}</b></td><td class=first>{E(s['first'][:90])}</td></tr>" for s in sessions)
tool_cards = ''.join(f"""<section><h2>{E(t)}</h2><div class="scroll"><table><tbody>
  <tr><td>Prompts</td><td class=n>{v['prompts']}</td></tr><tr><td>Total tokens</td><td class=n>{v['tokens']:,}</td></tr>
  <tr><td>Main agent / {'subagents' if t.startswith('Claude') else 'review'}</td><td class=n>{M(v['main'])} / {M(v['sub'])}</td></tr>
  <tr><td>Cached input</td><td class=n>{v['cached']:,}</td></tr><tr><td>Output tokens</td><td class=n>{v['out']:,}</td></tr>
  <tr><td>Agent runtime</td><td class=n>{hm(v['runtime'])}</td></tr></tbody></table></div>
  <p class="muted">Models: {E(', '.join(v['models']) or '—')}{('; helpers: ' + E(', '.join(v['sub_models']))) if v['sub_models'] else ''}. Runtime recorded for {v['runtime_recorded']} of {v['prompts']} prompts.</p></section>""" for t, v in d['tools'].items())
longest = ''.join(f"<tr><td class=n>{P(x['t']).strftime('%b %-d %-I:%M %p')}</td><td>{chips([x['tool']])}</td><td class=n>{hm(x['dur'])}</td><td class=p>{E(x['text'])}</td></tr>" for x in d['longest'])
log = ''
if not a.no_prompt_log:
    rows = ''.join(f"<tr><td class=n>{i}</td><td class=n>{P(p['t']).strftime('%b %-d %-I:%M:%S %p')}</td><td>{chips([p['tool']])}</td><td class=p>{E(p['text'][:220])}{'…' if len(p['text']) > 220 else ''}</td><td class=n>{p['tokens']:,}</td><td class=n>{'' if p['dur'] is None else hm(p['dur']) if p['dur'] >= 60 else str(round(p['dur'])) + 's'}</td><td class=n>{p['compose']}s</td></tr>" for i, p in enumerate(d['prompts'], 1))
    log = f"""<section><h2>Every prompt</h2><p class="muted">Tokens include cached input. Agent is how long the agent worked on the prompt; compose is the estimated time to write it.</p>
  <div class="scroll"><table><thead><tr><th>#</th><th>Time</th><th>Tool</th><th>Prompt</th><th>Tokens</th><th>Agent</th><th>Compose</th></tr></thead><tbody>{rows}</tbody></table></div></section>"""
T = d['total']; idle = d['idle']

page = f"""<title>{E(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: single ledger column; invoice first, then the work log that backs it */
:root {{ --bg:#f6f7f9; --panel:#ffffff; --fg:#1b2230; --muted:#5d6779; --line:#dde2ea; --accent:#2b4f86; --hl:#e9eef7;
  --claude:#b5562c; --codex:#1f8a6e; --you:#3a62a8; --agent:#b07a1e;
  --display:'Fraunces', Georgia, serif; --body:'IBM Plex Sans', system-ui, sans-serif; --mono:'IBM Plex Mono', ui-monospace, monospace; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#11151c; --panel:#181d26; --fg:#e4e8ef; --muted:#97a1b3; --line:#2a3240; --accent:#8fb0e6; --hl:#1f2a3b; --claude:#d97a4f; --codex:#3fb08f; --you:#6f97e0; --agent:#d19a3a; color-scheme:dark }} }}
:root[data-theme="dark"] {{ --bg:#11151c; --panel:#181d26; --fg:#e4e8ef; --muted:#97a1b3; --line:#2a3240; --accent:#8fb0e6; --hl:#1f2a3b; --claude:#d97a4f; --codex:#3fb08f; --you:#6f97e0; --agent:#d19a3a; color-scheme:dark }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.55 var(--body); padding-inline:16px; padding-block:32px 64px }}
main {{ max-width:1080px; margin:0 auto; display:grid; gap:40px }}
h1 {{ font:650 clamp(28px,5vw,40px)/1.1 var(--display); margin:0; text-wrap:balance }}
h2 {{ font:600 22px/1.2 var(--display); margin:0 0 12px; text-wrap:balance }}
p {{ margin:0; max-width:70ch }} .muted {{ color:var(--muted) }} b {{ font-weight:600 }}
.eyebrow {{ font:500 12px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--muted) }}
header {{ display:grid; gap:10px }}
.invoice {{ background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:28px clamp(16px,4vw,36px); display:grid; gap:24px }}
.inv-head {{ display:flex; flex-wrap:wrap; justify-content:space-between; gap:16px; align-items:end }}
.inv-head dl {{ display:grid; grid-template-columns:auto auto; gap:2px 16px; margin:0; font-size:14px }}
.inv-head dt {{ color:var(--muted) }} .inv-head dd {{ margin:0; font-family:var(--mono) }}
.parties {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px }}
.parties > div {{ display:grid; gap:2px; min-width:0 }}
.invoice .scroll {{ border:0; border-radius:0 }}
table.lines tfoot td {{ font-weight:600; border-top:2px solid var(--fg); border-bottom:0 }} td.total {{ font:600 20px var(--mono) }}
.r {{ text-align:right }}
.hero {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px }}
.hero > div {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px 20px; display:grid; gap:4px; min-width:0 }}
.hero .big {{ font:600 32px/1.1 var(--display); font-variant-numeric:tabular-nums }}
section {{ display:grid; gap:12px; min-width:0 }}
.scroll {{ overflow-x:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel) }}
table {{ border-collapse:collapse; width:100%; font-size:13.5px }}
th, td {{ text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ font:500 11.5px var(--mono); letter-spacing:.06em; text-transform:uppercase; color:var(--muted); background:var(--panel) }}
th.r, td.r {{ text-align:right }}
tbody tr:last-child td {{ border-bottom:0 }}
td.n {{ font-family:var(--mono); font-variant-numeric:tabular-nums; white-space:nowrap }}
td.p {{ min-width:280px; max-width:520px; word-break:break-word }} td.first {{ min-width:220px; color:var(--muted) }}
tr.rec td {{ background:var(--hl); font-weight:600 }}
.chip {{ display:inline-block; font:500 11px var(--mono); padding:2px 7px; border-radius:99px; border:1px solid currentColor; white-space:nowrap }}
.chip.claude {{ color:var(--claude) }} .chip.codex {{ color:var(--codex) }}
.two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:24px }}
ol {{ margin:0; padding-left:20px; display:grid; gap:6px; max-width:72ch }}
code {{ font:13px var(--mono) }}
.chart {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; display:grid; gap:10px; min-width:0 }}
.chart svg {{ width:100%; height:auto; display:block; overflow:visible }}
.chart text {{ fill:var(--muted); font:11px var(--mono) }} .chart text.lab {{ fill:var(--fg) }}
.chart .grid {{ stroke:var(--line); stroke-width:1 }} .chart .hit {{ fill:transparent }} .chart .hit:hover {{ fill:var(--hl); opacity:.6 }}
.legend {{ display:flex; flex-wrap:wrap; gap:6px 16px; font:12px var(--body); color:var(--muted) }}
.legend i {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; vertical-align:-1px }}
#tip {{ position:fixed; pointer-events:none; background:var(--fg); color:var(--bg); font:12px/1.4 var(--body); padding:6px 9px; border-radius:6px; max-width:280px; z-index:9 }}
.k-you {{ fill:var(--you); background:var(--you) }} .k-agent {{ fill:var(--agent); background:var(--agent) }} .k-claude {{ fill:var(--claude); background:var(--claude) }} .k-codex {{ fill:var(--codex); background:var(--codex) }}
</style>
<main>
{inv}
<header>
  <span class="eyebrow">{E(proj)} · {period} · {E(d['tz'])}</span>
  <h2 style="font-size:30px">Work log</h2>
  <p class="muted">Every prompt sent to {' and '.join(tools)} on this project, the tokens each one used, how long the agents worked, and how the billed hours were estimated.</p>
</header>
<div class="hero">
  <div><span class="eyebrow">Estimated time</span><span class="big">{hm(d['billable'])}</span><span class="muted">{d['billable'] / 3600:.2f} h · {idle:g}-min idle rule · {len(sessions)} sessions</span></div>
  <div><span class="eyebrow">Agent runtime</span><span class="big">{hm(d['agent_wall'])}</span><span class="muted">wall clock · {' · '.join(f"{t.split()[0]} {hm(v['runtime'])}" for t, v in d['tools'].items())}</span></div>
  <div><span class="eyebrow">Prompts</span><span class="big">{T['prompts']}</span><span class="muted">{' · '.join(f"{t} {v['prompts']}" for t, v in d['tools'].items())}</span></div>
  <div><span class="eyebrow">Tokens</span><span class="big">{M(T['tokens'])}</span><span class="muted">{' · '.join(f"{t.split()[0]} {M(v['tokens'])}" for t, v in d['tools'].items())}</span></div>
</div>
<section><h2>Your time and agent runtime</h2>
  <p class="muted">Per work session. Your time is the billable estimate; agent runtime is how long the agents were working, with overlapping runs counted once.</p>
  <div class="chart"><div class="legend"><span><i class="k-you"></i>Your time</span><span><i class="k-agent"></i>Agent runtime</span></div>{chart_time()}</div></section>
<section><h2>Tokens by session</h2>
  <div class="chart"><div class="legend">{''.join(f'<span><i class="{"k-claude" if t.startswith("Claude") else "k-codex"}"></i>{E(t)}</span>' for t in tools)}</div>{chart_tokens()}</div></section>
<section><h2>How the time is estimated</h2>
  <ol>
    <li>All prompts from every tool go on one timeline, plus keyboard actions that are not prompts (model switches, interrupts). Time when agents ran side by side is counted once.</li>
    <li>Prompts less than {idle:g} minutes apart belong to the same work session. Everything between a session's first and last prompt counts: reading output, checking the work, writing the next prompt.</li>
    <li>Each session gets a lead-in for writing its first prompt: 20 s, plus typing at about 40 wpm, plus 15 s per screenshot or file attached.</li>
    <li>Each session gets a tail after its last prompt: the time until the agent's answer came back, plus {d['tail']:g} minutes to review it, capped at {idle:g} minutes.</li>
    <li>Gaps longer than {idle:g} minutes are not billed, and long unattended agent runs only count up to the cap.</li>
  </ol>
  <p class="muted">The floor ({hm(d['floor'])}) ignores waiting entirely: composing time for each prompt plus one minute to read each answer.</p>
  <div class="scroll"><table><thead><tr><th>Idle rule</th><th>Sessions</th><th>Span</th><th>Lead-in</th><th>Tail (capped)</th><th>Total</th></tr></thead><tbody>{sens_rows}</tbody></table></div></section>
<section><h2>Work sessions</h2>
  <div class="scroll"><table><thead><tr><th>Date</th><th>Prompts span</th><th>Tools</th><th>Prompts</th><th>Tokens</th><th>Agent runtime</th><th>Lead-in</th><th>Tail</th><th>Billable</th><th>Opening prompt</th></tr></thead><tbody>{sess_rows}</tbody></table></div></section>
<section><h2>Longest agent runs</h2>
  <div class="scroll"><table><thead><tr><th>Started</th><th>Tool</th><th>Runtime</th><th>Prompt</th></tr></thead><tbody>{longest}</tbody></table></div></section>
<div class="two">{tool_cards}</div>
{log}
</main>
<div id="tip" hidden></div>
<script>
const tip = document.getElementById('tip');
document.querySelectorAll('[data-tip]').forEach(el => {{
  el.addEventListener('pointermove', e => {{ tip.innerHTML = el.dataset.tip; tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }});
  el.addEventListener('pointerleave', () => tip.hidden = true);
}});
</script>
"""
open(a.out, 'w').write(page)
print(f"wrote {a.out}: {hours:.2f} h × {money(a.rate)} = {money(total)} ({len(lines)} line items)")
