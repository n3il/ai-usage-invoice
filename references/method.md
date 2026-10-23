# How billed time is estimated

## Data sources

| Tool | Where | Prompts | Tokens | Agent runtime |
|---|---|---|---|---|
| Claude Code | `~/.claude/projects/<cwd with non-alphanumerics → '-'>/*.jsonl`, subagents in `<session>/subagents/` | `type:user` entries that are not tool results, meta, or command output. Skills (`/name args`) and `!` shell commands count as prompts; built-ins like `/model` and `/clear` and interrupts count only as keyboard activity | each assistant message's `usage`, deduped by message id, assigned to the latest earlier prompt in the same session; subagent usage assigned the same way by timestamp | `system/turn_duration` after the prompt, else last assistant reply minus prompt time |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` with `session_meta.cwd` inside the project | `response_item` user messages, minus environment/AGENTS.md wrappers | `token_usage_record.usage` (input includes cached); guardian-review rollouts (`parent_thread_id`) count as review usage on the parent's prompt | `task_started` → `task_complete` per turn; a prompt sent mid-turn ends the previous prompt's share |

Total tokens = input (uncached + cache writes + cache reads) + output, matching how Codex reports `total_tokens`.

## Work sessions

1. Put every prompt from every tool, plus non-prompt keyboard activity, on one timeline. Parallel tools therefore never double-bill.
2. Consecutive events no more than *idle* minutes apart (default 15) form one session.
3. **Span**: first to last prompt of the session, counted in full.
4. **Lead-in**: time to write the first prompt: 20 s + characters ÷ 3.33/s (≈40 wpm, capped at 2,000 chars) + 15 s per attached image.
5. **Tail**: from the last prompt until its answer finished, plus *tail* minutes (default 3) to review it, capped at the idle rule.
6. **Billable** = Σ (span + lead-in + tail).

**Floor**: Σ (compose time + 60 s) over all prompts. It assumes no time spent waiting or reviewing beyond one minute per answer; quote it as the lowest defensible figure.

**Agent runtime**: the union of [prompt, prompt + runtime] intervals, so overlapping agents count once. The per-tool sums are shown alongside.

## Choosing the idle rule

| Rule | Effect |
|---|---|
| 5 min | Too strict: counts you idle whenever an agent ran longer than 5 minutes, and many tails hit the cap. |
| 10 min | Conservative. |
| **15 min** | Common convention for activity-based time tracking; recommended default. |
| 20 min | Lenient. |
| 30 min | Bills short breaks; only defensible if the person stayed on the project. |

As the rule grows, span rises (more pauses count), lead-ins fall (fewer sessions) and tails mostly fall (fewer sessions, fewer capped). Explain differences in those terms.
