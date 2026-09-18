# Codex model choice — 2026-09-15 (rev. 2: GPT-6 Astra evaluated, see §Astra)

## What was compared

For this kit, **agentic coding with shell tools** matters more than a generic intelligence score: an agent must
look up FiveM natives, edit Lua/JS in small slices, run `fxlint`, and diagnose a real resource. I used
OpenAI's [GPT-5.6 launch report](https://openai.com/index/gpt-5-6/) (vendor benchmarks),
[Artificial Analysis's Coding Agent Index](https://artificialanalysis.ai/articles/gpt-5-6-has-landed)
(independently run, in Codex harness), [AA's Astra benchmarks](https://artificialanalysis.ai/articles/benchmarking-gpt-6-astra),
[Endor Labs' Agent Security League](https://www.endorlabs.com/learn/gpt-6-astra-on-codex---the-biggest-codex-leap-to-date),
and OpenAI's [Codex pricing/usage tables](https://learn.chatgpt.com/docs/pricing)
for cost. These are not FiveM-specific tests or runs through this exact Codex adapter; model configuration and
agent harness can move the scores. Nothing below is 100000% certain — it is the best benchmark-informed default
plus the experiment that would overturn it (see §How this could be wrong).

Current Codex lineup (GPT-5.6 family, GA 2026-07-09; GPT-5.4/5.4-mini retired from Codex on 2026-08-31):

| Candidate | AA Coding Agent Index | Terminal-Bench 2.1 | SWE-Bench Pro | API price input/output per 1M | Plus msgs / 5h | Decision |
|---|---:|---:|---:|---:|---:|---|
| GPT-5.6 Terra | 77.4 | 87.4% | 63.4% | $2 / $12 | 25–200 | Coordinator, implementer, reviewer. |
| GPT-5.6 Luna | 74.6 | 84.7% | 62.7% | $0.20 / $1.20 | 250–2,000 | Native scout (mechanical, `fxref`-verified). |
| GPT-5.6 Sol | 80 | 88.8% | 64.6% | $4 / $20 promo*; list $5 / $30 | 10–100 | Explicit deep-reviewer second opinion only. |

\* Sol's promotional pricing runs at least through November 21, 2026, then reverts to list. All three tiers share
a 1.05M-token context, 128K max output, and a February 16, 2026 knowledge cutoff. Requests whose input exceeds
272K tokens are billed at 2× input / 1.5× output for the whole request — keep contexts below that line.
Cached-input reads get a 90% discount on all tiers, so pinning the rulebook/skills in cache narrows the cost gap
further. Prices and quotas change; recheck the [rate card](https://learn.chatgpt.com/docs/pricing) before
sensitive work.

### Why Terra by default

Terra sits 2.6 points behind Sol on the Coding Agent Index and 1.4 points behind on Terminal-Bench 2.1 — the
benchmark closest to this kit's shell-driven workflow — at half Sol's per-token price and ~2–3× the usage
allowance. OpenAI positions Terra as "better than GPT-5.5 at half of Sol's price", and independent routing
guides converge on the same rule: **Terra as the daily default, Sol only where evals show the task earns it,
Luna for mechanical high-volume work**. A vendor-run harness caveat: on very long jobs Sol can be more
token-efficient (fewer retries), so a Terra run that stalls should escalate to Sol rather than burn more Terra
turns.

### Why Luna for the scout

The scout never writes code: it runs `fxref search/show/resolve` and copies signatures off the cards. Its output
is mechanically verifiable (`fxref resolve` either confirms a name or reports MISSING), so the capability gap to
Terra/Sol buys almost nothing while costing 10×/25× per token. Luna still scores 84.7% on Terminal-Bench 2.1 and
gets the largest usage allowance (250–2,000 msgs/5h on Plus), which is what a fan-out lookup role wants.

### Why Sol stays explicit-only

Sol is the strongest coding model in the lineup (Coding Agent Index 80, Terminal-Bench 91.9% at ultra effort) but
has the smallest allowance (10–100 msgs/5h) and the highest price. In a multi-turn lint/review pipeline it is
best reserved for explicit, high-value second opinions on difficult or security-sensitive reviews — the same role
Kimi K3 filled in the OpenCode adapter.

## Resulting role policy

- **Coordinator (main session + `fivem` / `fivem-core` agents):** `gpt-5.6-terra`, high effort — plans,
  delegates to subagents, verifies.
- **Scout:** `gpt-5.6-luna`, medium effort — reference search, mechanically checked with `fxref`.
- **Implementer:** `gpt-5.6-terra`, high effort — bounded slices (≤4 files / ~600 lines); escalate a stalled
  slice once to `gpt-6-astra` (fallback: Sol) rather than retrying indefinitely.
- **Reviewer:** `gpt-5.6-terra`, high effort — checklist/security review; the coordinator still re-runs `fxlint`
  and spot-checks natives.
- **Deep reviewer:** `gpt-6-astra`, high effort — explicit second opinion only, never routine; fallback
  `gpt-5.6-sol` where Astra is unavailable (see §Astra).

Unlike the OpenCode adapter (DeepSeek vs. GLM = different model families), the routine Codex roles share the
GPT-5.6 family, so reviewer independence comes from the separate checklist pass plus the coordinator's own
`fxlint` / `fxref` re-verification, not from model diversity. This is a **benchmark-informed starting
configuration**, not a claim of proven FiveM superiority.

## §Astra — GPT-6 Astra (shipped 2026-09-03, evaluated 2026-09-15)

Astra (`gpt-6-astra`, knowledge cutoff 2026-04-30, needs Codex CLI ≥ 0.153.0) is the first model since the 5.6
family that moves the top end for Codex agentic work:

| Signal | Astra | Sol | Source |
|---|---|---|---|
| AA Coding Agent Index | 67 | 65 | Artificial Analysis, Codex harness |
| Token use in Codex harness | ~⅓ of Sol | 1× | AA — per-task cost lands near Sol despite $10/$50 sticker (2.5×/token) |
| Terminal-Bench 4.0 | 57.7–57.9% | 37.3% | OpenAI / Codex Knowledge Base (Fable 5.1: 55.8%) |
| FuncPass / SecPass (real-world security tasks) | 82.1% / 34.1% | 67.6% / 20.1% | Endor Labs, same Codex harness, 0 confirmed cheats |
| Speed | ~1.8× slower, ~3× timeouts vs Sol | baseline | Endor Labs — reliability tradeoff is real |

Consequences for this kit: the **SecPass jump (+14 pts, directly security-review-shaped)** makes Astra the right
explicit second opinion, replacing Sol as `fivem-deep-reviewer`. Start it at **high**, not max — AA measured max
as ~2× the cost for +1 Intelligence Index point. The routine roles stay Terra: Astra's per-task cost is
Sol-class, not Terra-class, and its latency/timeouts are wrong for high-frequency implementer loops.

Availability caveats (staged rollout): not in the picker by default on old CLIs (0.153.4, this machine's
version, fixes picker visibility and falls back to Astra when no model is configured); Enterprise/Edu needs an
admin to enable it; Plus/Business Standard get limited Codex usage; Free/Go get none. Check with `/model` or
`codex models`. **If your account lacks Astra, set `fivem-deep-reviewer` and the `deep-review` profile back to
`gpt-5.6-sol`** — still a defensible second opinion (Coding Agent Index 80 v1.1, TB 2.1 88.8%).

## How this could be wrong

1. **Terra's gap is benchmark-dependent.** On TB 2.1-era coding tasks Terra trails Sol by ~1–2 pts; on the newer,
   harder Terminal-Bench 4.0, AA's Sol(max)-vs-Terra(high) comparison shows 40% vs 2%, and CodeRabbit's
   long-horizon harness shows Sol 63.7% vs Terra 40.7% pass with Terra burning 2.7× output tokens. If FiveM
   slices turn out to be "long-horizon" rather than "bounded" in practice, Terra-first loses and the default
   should move up.
2. **No FiveM-specific measurement exists yet.** The decisive experiment: run the same 3–5 small FiveM tasks
   (scaffold → implement → lint → review) through Luna/Terra/Sol(/Astra where available) in this adapter and
   score `fxlint` errors, native-resolution accuracy, functional behavior, tokens, wall time, and retries. A few
   dollars of API credit settles what no benchmark table can.
3. **Prices, quotas, and promotions move.** Sol's promo runs through 2026-11-21; the 272K-input 2×/1.5× cliff
   applies per request; Astra access is still rolling out. Recheck the rate card when bills look surprising.
