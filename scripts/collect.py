#!/usr/bin/env python3
"""Collect Claude Code + Codex prompt/token/runtime data for one project and estimate billable time.

Usage:
  collect.py --project /abs/path/to/repo --out DIR [--since YYYY-MM-DD] [--until YYYY-MM-DD]
             [--tz IANA_TIMEZONE] [--idle 15] [--tail 3]
             [--exclude-prompt REGEX ...] [--exclude-session ID ...] [--exclude-current]
             [--codex-csv FILE ...] [--no-codex] [--no-claude]

Writes DIR/usage.json (everything build_report.py needs) and DIR/prompts.csv (one row per prompt, both tools).
"""
import argparse, csv, datetime as dt, glob, json, os, re
from zoneinfo import ZoneInfo

ap = argparse.ArgumentParser()
ap.add_argument('--project', required=True)
ap.add_argument('--out', required=True)
ap.add_argument('--since'); ap.add_argument('--until')
ap.add_argument('--tz', help='IANA timezone; defaults to the system timezone')
ap.add_argument('--idle', type=float, default=15, help='minutes of inactivity that end a work session')
ap.add_argument('--tail', type=float, default=3, help='minutes to review the final answer of a session')
ap.add_argument('--exclude-prompt', action='append', default=[], help='regex (case-insensitive) on prompt text')
ap.add_argument('--exclude-session', action='append', default=[], help='Claude session id or Codex thread id')
ap.add_argument('--exclude-current', action='store_true', help='drop the most recently modified Claude transcript (the session running this)')
ap.add_argument('--codex-csv', action='append', default=[], help='Codex usage export CSV, used instead of ~/.codex logs')
ap.add_argument('--no-codex', action='store_true'); ap.add_argument('--no-claude', action='store_true')
a = ap.parse_args()

def system_timezone():
    candidates = [os.environ.get('TZ', '').lstrip(':')]
    localtime = os.path.realpath('/etc/localtime')
    if '/zoneinfo/' in localtime:
        candidates.append(localtime.split('/zoneinfo/', 1)[1])
    try:
        with open('/etc/timezone') as f:
            candidates.append(f.read().strip())
    except OSError:
        pass
    for name in candidates:
        if not name:
            continue
        try:
            return ZoneInfo(name).key
        except (ValueError, KeyError):
            pass
    ap.error('Cannot detect the system timezone; pass --tz with an IANA timezone (e.g. Europe/London).')

if not a.tz:
    a.tz = system_timezone()
try:
    TZ = ZoneInfo(a.tz)
except (ValueError, KeyError):
    ap.error(f'Unknown timezone: {a.tz}; pass an IANA timezone.')
PROJECT = os.path.realpath(os.path.expanduser(a.project))
os.makedirs(a.out, exist_ok=True)
def ts(s): return dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
def epoch(x): return dt.datetime.fromtimestamp(x, dt.timezone.utc)
SINCE = dt.datetime.fromisoformat(a.since).replace(tzinfo=TZ) if a.since else None
UNTIL = (dt.datetime.fromisoformat(a.until).replace(tzinfo=TZ) + dt.timedelta(days=1)) if a.until else None
EXCL = [re.compile(r, re.I) for r in a.exclude_prompt]
def in_range(t): return (not SINCE or t >= SINCE) and (not UNTIL or t < UNTIL)
def excluded_text(t): return any(r.search(t or '') for r in EXCL)

prompts = []     # dict(tool, session, t, end, dur, kind, text, images, models, sub_models, tokens...)
activity = []    # timestamps of keyboard actions that are not prompts (/model, interrupts, ...)

def new_prompt(tool, session, t, kind, text, images):
    return dict(tool=tool, session=session, t=t, end=t, dur=None, kind=kind, text=text, images=images,
                models=set(), sub_models=set(), inp=0, cw=0, cr=0, out=0, think=0,
                s_inp=0, s_cw=0, s_cr=0, s_out=0, s_think=0, last_reply=None)

def attribute(plist, t):
    best = None
    for p in plist:
        if p['t'] <= t: best = p
        else: break
    return best

# ---------------- Claude Code ----------------
BUILTIN = {'model', 'clear', 'exit', 'plugin', 'permissions', 'reload-plugins', 'goal', 'config', 'compact', 'resume',
           'usage', 'cost', 'status', 'help', 'login', 'logout', 'doctor', 'memory', 'agents', 'mcp', 'hooks', 'fast', 'vim', 'theme'}
def classify_claude(d):
    c = d['message']['content']
    if isinstance(c, list):
        if any(x.get('type') == 'tool_result' for x in c): return None, None, 0
        imgs = sum(1 for x in c if x.get('type') == 'image')
        t = '\n'.join(x.get('text', '') for x in c if x.get('type') == 'text')
    else: t, imgs = c, 0
    s = t.strip()
    if s.startswith('[Request interrupted'): return 'interrupt', s, imgs
    if s.startswith(('<local-command-stdout>', '<bash-stdout>', '<task-notification>', '<local-command-caveat>', '<system-reminder>')): return None, s, imgs
    if s.startswith('<bash-input>'): return 'shell', re.sub(r'</?bash-input>', '', s).strip(), imgs
    m = re.search(r'<command-name>/?([^<]+)</command-name>', s)
    if m:
        name = m.group(1).strip()
        args = re.search(r'<command-args>(.*?)</command-args>', s, re.S)
        args = args.group(1).strip() if args else ''
        return ('command' if name in BUILTIN else 'skill'), '/' + name + (' ' + args if args else ''), imgs
    return 'prompt', s, imgs

if not a.no_claude:
    slug = re.sub(r'[^A-Za-z0-9]', '-', PROJECT)
    cdir = os.path.expanduser(f'~/.claude/projects/{slug}')
    files = sorted(glob.glob(f'{cdir}/*.jsonl'), key=os.path.getmtime)
    if a.exclude_current and files: a.exclude_session.append(os.path.basename(files[-1])[:-6])
    for f in files:
        sid = os.path.basename(f)[:-6]
        if sid in a.exclude_session: continue
        sp, usage, ends, seen = [], [], [], set()
        for l in open(f):
            d = json.loads(l)
            ty = d.get('type')
            if ty == 'user' and not d.get('isMeta') and not d.get('isSidechain'):
                kind, text, imgs = classify_claude(d)
                if kind is None: continue
                t = ts(d['timestamp'])
                if kind in ('prompt', 'skill', 'shell'): sp.append(new_prompt('Claude Code', sid, t, kind, text, imgs))
                else: activity.append(t)
            elif ty == 'assistant':
                m = d['message']; key = m.get('id') or d.get('requestId')
                if key in seen or not m.get('usage') or m.get('model') == '<synthetic>': continue
                seen.add(key); usage.append((ts(d['timestamp']), m['model'], m['usage'], False))
            elif ty == 'system' and d.get('subtype') == 'turn_duration':
                ends.append((ts(d['timestamp']), d['durationMs'] / 1000))
        for sf in glob.glob(f'{cdir}/{sid}/subagents/*.jsonl'):
            seen2 = set()
            for l in open(sf):
                d = json.loads(l)
                if d.get('type') != 'assistant': continue
                m = d['message']; key = m.get('id') or d.get('requestId')
                if key in seen2 or not m.get('usage'): continue
                seen2.add(key); usage.append((ts(d['timestamp']), m['model'], m['usage'], True))
        sp.sort(key=lambda p: p['t']); usage.sort(key=lambda u: u[0])
        for t, model, u, sub in usage:
            p = attribute(sp, t)
            if not p: continue
            pre = 's_' if sub else ''
            p[pre + 'inp'] += u.get('input_tokens', 0); p[pre + 'cw'] += u.get('cache_creation_input_tokens', 0)
            p[pre + 'cr'] += u.get('cache_read_input_tokens', 0); p[pre + 'out'] += u.get('output_tokens', 0)
            p[pre + 'think'] += (u.get('output_tokens_details') or {}).get('thinking_tokens', 0)
            (p['sub_models'] if sub else p['models']).add(model)
            if not sub and (p['last_reply'] is None or t > p['last_reply']): p['last_reply'] = t
        for t, sec in ends:
            p = attribute(sp, t)
            if p and p['dur'] is None: p['dur'] = sec
        for p in sp:
            if p['dur'] is None and p['last_reply']: p['dur'] = (p['last_reply'] - p['t']).total_seconds()
        prompts += sp

# ---------------- Codex ----------------
def codex_text(content):
    parts, imgs = [], 0
    for x in content:
        if x.get('type') == 'input_image': imgs += 1
        elif x.get('type') == 'input_text':
            t = re.sub(r'<image name=[^>]*>', '', x.get('text', '')).strip()
            if t: parts.append(t)
    return '\n'.join(parts).strip(), imgs

if not a.no_codex and a.codex_csv:
    for fn in a.codex_csv:
        rows = list(csv.DictReader(open(fn)))
        bythread = {}
        for r in rows:
            t = dt.datetime.strptime(r['timestamp_america_new_york'].split(' GMT')[0], '%a %b %d %Y %H:%M:%S').replace(tzinfo=ZoneInfo('America/New_York'))
            if r.get('conversation_id') in a.exclude_session: continue
            p = new_prompt('Codex', r.get('conversation_id', ''), t, 'prompt', r['prompt'], len(re.findall(r'\[Image #\d+\]', r['prompt'])))
            i = lambda k: int(r.get(k) or 0)
            p.update(inp=i('input_tokens') - i('cached_input_tokens'), cr=i('cached_input_tokens'), out=i('output_tokens'), think=i('reasoning_output_tokens'),
                     s_inp=i('review_input_tokens') - i('review_cached_input_tokens'), s_cr=i('review_cached_input_tokens'), s_out=i('review_output_tokens'), s_think=i('review_reasoning_output_tokens'))
            if r['model'] and not r['model'].startswith('no recorded'): p['models'].add(r['model'])
            if r.get('review_model'): p['sub_models'].add(r['review_model'])
            p['dur'] = float(r['assistant_turn_seconds']) if r.get('assistant_turn_seconds') else None
            p['turn'] = r.get('turn_id')
            bythread.setdefault(p['session'], []).append(p)
        prompts += [p for v in bythread.values() for p in v]
elif not a.no_codex:
    threads, reviews = {}, {}
    for f in glob.glob(os.path.expanduser('~/.codex/sessions/**/rollout-*.jsonl'), recursive=True):
        with open(f) as fh:
            first = fh.readline()
            try: meta = json.loads(first)['payload']
            except Exception: continue
            cwd = os.path.realpath(meta.get('cwd') or '')
            if cwd != PROJECT and not cwd.startswith(PROJECT + os.sep): continue
            tid = meta.get('id') or meta.get('session_id')
            parent = meta.get('parent_thread_id')
            is_review = bool(parent) and meta.get('thread_source') != 'user'
            rec = dict(prompts=[], usage=[], turns={}, models={}, parent=parent)
            cur_turn = None
            for l in [first] + fh.readlines():
                d = json.loads(l); p = d.get('payload', {}); ty = d.get('type')
                if ty == 'turn_context':
                    cur_turn = p.get('turn_id'); rec['models'][cur_turn] = p.get('model')
                elif ty == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user' and not is_review:
                    text, imgs = codex_text(p.get('content', []))
                    if not text and not imgs: continue
                    if text.startswith(('<environment_context>', '# AGENTS.md', '<user_instructions>', '<permissions', '<turn_aborted>')): continue
                    turn = (p.get('internal_chat_message_metadata_passthrough') or {}).get('turn_id') or cur_turn
                    q = new_prompt('Codex', tid, ts(d['timestamp']), 'prompt', text, imgs); q['turn'] = turn
                    rec['prompts'].append(q)
                elif ty == 'token_usage_record':
                    rec['usage'].append((ts(d['timestamp']), p.get('turn_id'), p.get('usage') or {}))
                elif ty == 'event_msg' and p.get('type') == 'task_started':
                    rec['turns'].setdefault(p['turn_id'], {})['start'] = epoch(p['started_at']) if p.get('started_at') else ts(d['timestamp'])
                elif ty == 'event_msg' and p.get('type') == 'task_complete':
                    rec['turns'].setdefault(p['turn_id'], {})['end'] = epoch(p['completed_at']) if p.get('completed_at') else ts(d['timestamp'])
            (reviews if is_review else threads)[tid] = rec
    for tid, rec in threads.items():
        if tid in a.exclude_session: continue
        sp = sorted(rec['prompts'], key=lambda q: q['t'])
        for t, turn, u in sorted(rec['usage'], key=lambda x: x[0]):
            q = attribute(sp, t)
            if not q: continue
            q['inp'] += u.get('input_tokens', 0) - u.get('cached_input_tokens', 0); q['cr'] += u.get('cached_input_tokens', 0)
            q['cw'] += u.get('cache_write_input_tokens', 0); q['out'] += u.get('output_tokens', 0); q['think'] += u.get('reasoning_output_tokens', 0)
            if rec['models'].get(turn): q['models'].add(rec['models'][turn])
        for rid, rv in reviews.items():
            if rv['parent'] != tid: continue
            for t, turn, u in rv['usage']:
                q = attribute(sp, t)
                if not q: continue
                q['s_inp'] += u.get('input_tokens', 0) - u.get('cached_input_tokens', 0); q['s_cr'] += u.get('cached_input_tokens', 0)
                q['s_cw'] += u.get('cache_write_input_tokens', 0); q['s_out'] += u.get('output_tokens', 0); q['s_think'] += u.get('reasoning_output_tokens', 0)
                q['sub_models'].add('codex review' + (f" ({rv['models'].get(turn)})" if rv['models'].get(turn) else ''))
        # runtime: a turn runs from task_started to task_complete; prompts sent mid-turn (steering) split it
        for i, q in enumerate(sp):
            tr = rec['turns'].get(q.get('turn'), {})
            if 'end' not in tr: continue
            nxt = next((r for r in sp[i + 1:] if r.get('turn') == q.get('turn')), None)
            end = nxt['t'] if nxt else tr['end']
            q['dur'] = max((end - q['t']).total_seconds(), 0)
        prompts += sp

# ---------------- filter, totals ----------------
for p in prompts:
    p['excluded'] = excluded_text(p['text']) or not in_range(p['t'])
    p['end'] = p['t'] + dt.timedelta(seconds=p['dur'] or 0)
    p['tokens_main'] = p['inp'] + p['cw'] + p['cr'] + p['out']
    p['tokens_sub'] = p['s_inp'] + p['s_cw'] + p['s_cr'] + p['s_out']
    p['tokens'] = p['tokens_main'] + p['tokens_sub']
removed = [p for p in prompts if p['excluded']]
prompts = sorted([p for p in prompts if not p['excluded']], key=lambda p: p['t'])
activity = [t for t in activity if in_range(t)]

# ---------------- time estimate ----------------
CPS = 200 / 60  # typing ~40 wpm
def compose_s(p): return 20 + min(len(p['text']), 2000) / CPS + 15 * p['images']
def union_s(ps):
    iv = sorted((p['t'], p['end']) for p in ps if p['dur'])
    tot, cs, ce = 0.0, None, None
    for s, e in iv:
        if cs is None or s > ce:
            if cs is not None: tot += (ce - cs).total_seconds()
            cs, ce = s, e
        else: ce = max(ce, e)
    if cs is not None: tot += (ce - cs).total_seconds()
    return tot
def sessions(idle_min, tail_min):
    idle, tail = dt.timedelta(minutes=idle_min), dt.timedelta(minutes=tail_min)
    pts = sorted([(p['t'], p) for p in prompts] + [(t, None) for t in activity], key=lambda x: x[0])
    out, cur = [], None
    for t, p in pts:
        if cur and t - cur['last'] <= idle: cur['last'] = t
        else:
            if cur: out.append(cur)
            cur = dict(start=t, last=t, lead=compose_s(p) if p else 20, prompts=[], result_end=t)
        if p: cur['prompts'].append(p); cur['result_end'] = max(cur['result_end'], p['end'])
    if cur: out.append(cur)
    out = [s for s in out if s['prompts']]
    for s in out:
        s['span'] = (s['last'] - s['start']).total_seconds()
        s['tail'] = min(max((s['result_end'] - s['last']).total_seconds(), 0) + tail.total_seconds(), idle.total_seconds())
        s['billable'] = s['span'] + s['lead'] + s['tail']
    return out

def iso(t): return t.astimezone(TZ).isoformat()
sens = []
for th in sorted({5, 10, 15, 20, 30, a.idle}):
    ss = sessions(th, a.tail)
    sens.append(dict(idle=th, sessions=len(ss), span=sum(s['span'] for s in ss), lead=sum(s['lead'] for s in ss),
                     tail=sum(s['tail'] for s in ss), capped=sum(1 for s in ss if s['tail'] >= th * 60), billable=sum(s['billable'] for s in ss)))
main = sessions(a.idle, a.tail)
tools = sorted({p['tool'] for p in prompts})
def tot(ps):
    return dict(prompts=len(ps), tokens=sum(p['tokens'] for p in ps), main=sum(p['tokens_main'] for p in ps), sub=sum(p['tokens_sub'] for p in ps),
                cached=sum(p['cr'] + p['s_cr'] for p in ps), cache_write=sum(p['cw'] + p['s_cw'] for p in ps), out=sum(p['out'] + p['s_out'] for p in ps),
                runtime=sum(p['dur'] or 0 for p in ps), runtime_recorded=sum(1 for p in ps if p['dur'] is not None),
                models=sorted({m for p in ps for m in p['models']}), sub_models=sorted({m for p in ps for m in p['sub_models']}))
data = dict(
    project=PROJECT, tz=a.tz, idle=a.idle, tail=a.tail, generated=dt.datetime.now(TZ).isoformat(),
    range=dict(first=iso(prompts[0]['t']) if prompts else None, last=iso(prompts[-1]['t']) if prompts else None),
    billable=sum(s['billable'] for s in main), floor=sum(compose_s(p) + 60 for p in prompts),
    agent_wall=union_s(prompts), sensitivity=sens, tools={t: tot([p for p in prompts if p['tool'] == t]) for t in tools}, total=tot(prompts),
    sessions=[dict(start=iso(s['start']), last=iso(s['last']), span=s['span'], lead=s['lead'], tail=s['tail'], billable=s['billable'],
                   n=len(s['prompts']), tools=sorted({p['tool'] for p in s['prompts']}), agent_wall=union_s(s['prompts']),
                   tokens={t: sum(p['tokens'] for p in s['prompts'] if p['tool'] == t) for t in tools},
                   first=s['prompts'][0]['text'][:120]) for s in main],
    longest=[dict(tool=p['tool'], t=iso(p['t']), dur=p['dur'], text=p['text'][:160]) for p in sorted(prompts, key=lambda p: -(p['dur'] or 0))[:5] if p['dur']],
    prompts=[dict(tool=p['tool'], session=p['session'], t=iso(p['t']), kind=p['kind'], text=p['text'], images=p['images'], tokens=p['tokens'],
                  dur=p['dur'], compose=round(compose_s(p))) for p in prompts],
    excluded=[dict(tool=p['tool'], t=iso(p['t']), text=p['text'][:200]) for p in removed],
    excluded_sessions=a.exclude_session,
)
json.dump(data, open(os.path.join(a.out, 'usage.json'), 'w'), indent=1)

cols = ['n', 'tool', 'timestamp', 'prompt', 'kind', 'images', 'model', 'input_tokens', 'cache_write_input_tokens', 'cached_input_tokens', 'output_tokens',
        'reasoning_output_tokens', 'total_tokens', 'sub_model', 'sub_input_tokens', 'sub_cached_input_tokens', 'sub_output_tokens', 'sub_total_tokens',
        'combined_total_tokens', 'agent_runtime_seconds', 'session_id']
with open(os.path.join(a.out, 'prompts.csv'), 'w', newline='') as fh:
    w = csv.writer(fh, quoting=csv.QUOTE_ALL); w.writerow(cols)
    for i, p in enumerate(prompts, 1):
        w.writerow([i, p['tool'], iso(p['t']), p['text'], p['kind'], p['images'], ', '.join(sorted(p['models'])), p['inp'] + p['cw'] + p['cr'], p['cw'], p['cr'],
                    p['out'], p['think'], p['tokens_main'], ', '.join(sorted(p['sub_models'])), p['s_inp'] + p['s_cw'] + p['s_cr'], p['s_cr'], p['s_out'],
                    p['tokens_sub'], p['tokens'], '' if p['dur'] is None else round(p['dur'], 3), p['session']])

def hm(s): s = int(round(s)); return f'{s // 3600}h {s % 3600 // 60:02d}m'
per_tool = ', '.join('%s %d' % (t, v['prompts']) for t, v in data['tools'].items())
print(f"prompts: {len(prompts)} ({per_tool}); excluded {len(removed)}")
print(f"billable ({a.idle:g}-min idle): {hm(data['billable'])} in {len(main)} sessions · floor {hm(data['floor'])} · agent runtime {hm(data['agent_wall'])}")
for s in sens: print(f"  idle {s['idle']:>4g}m: {hm(s['billable'])} ({s['sessions']} sessions)")
for t, v in data['tools'].items(): print(f"  {t}: {v['tokens']:,} tokens, runtime {hm(v['runtime'])} ({v['runtime_recorded']}/{v['prompts']} recorded)")
