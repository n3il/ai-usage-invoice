# AI Usage Invoice

Turn local Claude Code and Codex logs into an HTML client invoice, with a work log showing prompts, token usage, agent runtime, and estimated billable hours.

Use it as an agent skill via [SKILL.md](SKILL.md), or run the Python scripts directly. Requires Python 3.9+ and IANA timezone data; the scripts use only the Python standard library.

## Quick start

Clone the repository and run the collector for the project you want to invoice:

```bash
git clone https://github.com/n3il/ai-usage-invoice.git
cd ai-usage-invoice

python3 scripts/collect.py \
  --project /absolute/path/to/client-project \
  --out /tmp/client-invoice \
  --since 2026-09-01 \
  --until 2026-09-30
```

Dates are inclusive. Omit them to include all available activity. The collector uses your system timezone; pass `--tz America/New_York` (or another IANA timezone) to override it.

Review `/tmp/client-invoice/usage.json` and `prompts.csv` for unrelated work before building the invoice:

```bash
python3 scripts/build_invoice.py \
  --usage /tmp/client-invoice/usage.json \
  --out /tmp/client-invoice/invoice.html \
  --client "Example Client" \
  --rate 150 \
  --currency USD \
  --project-name "Client Project" \
  --from-name "Your Studio" \
  --from-detail "billing@example.com" \
  --no-prompt-log
```

Open `invoice.html` in a browser. It includes daily invoice lines, summary figures, charts, work sessions, and the estimation method. Omit `--no-prompt-log` to include the raw prompt log.

## Data sources and outputs

The collector reads Claude Code transcripts from `~/.claude/projects` and Codex rollouts from `~/.codex/sessions` for the selected project. It includes Claude subagent usage and Codex guardian-review usage when present. It does not read Hermes logs.

| Output | Contents |
| --- | --- |
| `usage.json` | Collected usage, prompts, sessions, and time estimates used by the invoice builder |
| `prompts.csv` | One row per prompt across both tools |
| `invoice.html` | Invoice and supporting work log |

Processing runs locally. The generated HTML references Google Fonts. Raw prompts remain in the JSON and CSV even when `--no-prompt-log` hides them in the HTML; review those files before sharing them.

## How hours are estimated

Billable hours are estimates from activity timestamps, not measured hands-on time. Prompts from both tools share one timeline, so parallel tool use does not double-count session time.

- Events no more than 15 minutes apart form a work session by default.
- Each session includes its prompt-to-prompt span, an estimated first-prompt writing time, and a capped final-answer/review tail.
- Agent runtime is reported separately, with overlapping runtime intervals counted once.
- The invoice charges estimated hours × your hourly rate; token counts are supporting usage data, not API charges.

See [the full method](references/method.md) for formulas, data-source details, and idle-rule comparisons.

## Useful options

| Script | Option | Purpose |
| --- | --- | --- |
| Collector | `--exclude-prompt 'regex'` | Exclude matching prompts; repeatable and case-insensitive |
| Collector | `--exclude-session ID` | Exclude a Claude session or Codex thread; repeatable |
| Collector | `--exclude-current` | Exclude the most recently modified Claude transcript for the project; use an explicit session ID for Codex |
| Collector | `--idle 10 --tail 3` | Adjust session gap and final review time in minutes |
| Collector | `--no-claude` / `--no-codex` | Read only the other tool's logs |
| Collector | `--codex-csv export.csv` | Use a Codex CSV export instead of Codex logs; exports lack full turn durations |
| Builder | `--basis floor` | Use the lower estimate based on prompt composition plus one minute per answer |
| Builder | `--round 0.25` | Round each day's hours up to the next quarter hour |
| Builder | `--invoice-number INV-2026-014` | Set an invoice identifier |
| Builder | `--due-days 30` | Change the default 14-day payment term |
| Builder | `--notes "Payment details"` | Add invoice notes |
| Builder | `--no-invoice` | Generate a work log without invoice amounts |

Run either script with `--help` for all available options.

## Use as an agent skill

Place this repository in your agent's skill directory, preserving `SKILL.md`, `scripts/`, and `references/` together. Ask the agent to create an invoice for a project and provide the client name, hourly rate, and billing period. [SKILL.md](SKILL.md) guides input collection, usage review, invoice generation, and delivery.
