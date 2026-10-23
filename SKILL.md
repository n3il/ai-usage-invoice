---
name: ai-usage-invoice
description: Build a client invoice from AI coding usage. Reads Claude Code transcripts (~/.claude/projects) and Codex logs (~/.codex/sessions) for one project, works out tokens, agent runtime and estimated hands-on hours, and generates an HTML invoice with a work log and charts behind it. Use when the user wants to bill or invoice a client for AI-assisted work, estimate time spent prompting, or report token usage and agent runtime for a project.
---

# AI usage invoice

Turns the prompt logs of Claude Code and Codex into an invoice for a client. Billed hours are estimated from prompt timestamps; the method is in `references/method.md`. Read it before explaining or changing the numbers.

## 1. Collect inputs

Required, ask only for what you can't infer:
- **Project directory**: default to the current working directory.
- **Client name** and **hourly rate**: never guess either.
- **Period**: default to all logged activity. Ask if the user mentions a previous invoice.

Optional, use defaults unless the user says otherwise: currency (USD), invoice number (`INV-YYYYMMDD`), issue date (today), due in 14 days, idle rule 15 min, rounding (none; suggest 0.25 h), sender name and details (ask once; save to memory if the user agrees).

## 2. Collect usage

Resolve `SKILL_DIR` to the directory containing this `SKILL.md`, wherever the skill is installed. Use that absolute path for both scripts; keep the working directory set to the project. Choose a temporary output directory for `<scratchpad>/invoice`.

The collector defaults to the system timezone. Pass `--tz <IANA timezone>` when the user requests a different timezone or automatic detection is unavailable. These scripts read Claude Code and Codex logs, not Hermes usage logs.

```bash
python3 "$SKILL_DIR/scripts/collect.py" \
  --project "$PWD" --out <scratchpad>/invoice --exclude-current \
  [--since 2026-09-01 --until 2026-09-30] [--exclude-prompt "regex"] [--exclude-session ID] \
  [--codex-csv export.csv]
```

- `--exclude-current` drops this session's transcript (making the invoice isn't billable work).
- Codex is read from `~/.codex/sessions` rollouts whose `cwd` is inside the project. Those logs carry full turn durations and the guardian-review usage. Use `--codex-csv` only if the user supplies an export and the logs are gone; the CSV lacks durations for turns shared by several prompts.
- Output: `usage.json` (input for step 4) and `prompts.csv` (one row per prompt, both tools).

## 3. Review before billing

Read the printed summary and scan `usage.json` → `prompts` for work that isn't this client's: other projects' scripts, personal questions, sessions that only prepared an invoice or report. List anything doubtful and ask the user. Re-run with `--exclude-prompt` / `--exclude-session` for what they drop. Never mention exclusions on the client-facing page.

## 4. Build the invoice

```bash
python3 "$SKILL_DIR/scripts/build_invoice.py" \
  --usage <scratchpad>/invoice/usage.json --out <scratchpad>/invoice/<project>-invoice.html \
  --client "Client" --rate 150 --project-name "site.com" \
  --from-name "Studio" --from-detail "email · address" \
  [--invoice-number INV-2026-014] [--round 0.25] [--basis floor] [--notes "Payment details…"] \
  [--no-prompt-log] [--no-invoice]
```

- One invoice line per day: hours × rate. `--round` rounds each day up.
- `--basis floor` bills the lower bound (writing prompts and reading answers only) instead of the session estimate.
- `--no-prompt-log` hides the raw prompt text. Offer it when prompts mention other clients, credentials or anything private.
- `--no-invoice` produces only the work log (usage report without amounts).

The page contains the invoice, then the work log behind it: summary tiles, a chart of your time against agent runtime per session, tokens per session by tool, the method with an idle-rule comparison table, sessions, longest agent runs, per-tool usage, and the prompt log.

## 5. Deliver

Save the HTML file and provide a clickable file link or attachment supported by the current environment. If the user requests hosting or sharing, use their chosen destination and report its actual access settings; do not assume a particular publishing service or Share menu. Report in your reply: total hours, amount, sessions, period, agent runtime, and anything you excluded. Copy `prompts.csv` next to the project's other outputs only if the user asks for files in the repo.

## Explaining the numbers

When asked how hours were derived or how idle rules compare, use the `sensitivity` array in `usage.json`. Each entry is span + lead-in + tail = billable for one idle rule. `references/method.md` explains each part and which rule to recommend.
