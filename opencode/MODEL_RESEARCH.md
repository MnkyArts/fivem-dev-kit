# OpenCode Go model choice — 2026-09-13

## What was compared

For this kit, **agentic coding with shell tools** matters more than a generic intelligence score: an agent must
look up FiveM natives, edit Lua/JS in small slices, run `fxlint`, and diagnose a real resource. I used
[Artificial Analysis's independently run Terminal-Bench v4.0 and SciCode results](https://artificialanalysis.ai/evaluations/terminalbench-v4-0)
as quality proxies, and [OpenCode Go's own allowance page](https://opencode.ai/go) for cost. These are not
FiveM-specific tests or runs through this exact OpenCode adapter; model configuration and agent harness can
move the scores. The public Go page currently shows a **temporary 4× DeepSeek V4.1 Flash allowance**; the
[detailed Go docs](https://opencode.ai/docs/go/) still show the pre-promotion number, so the promotion may end.

| Candidate | AA Terminal-Bench v4.0 | AA SciCode | Go estimated requests / 5h | Go monthly usage allowance | Decision |
|---|---:|---:|---:|---:|---|
| GLM-5.3-Flash | 33% | 52% | 6,320 | $60 | Main implementation model. |
| DeepSeek V4.1 Flash | 27% | 52% | 26,000 **temporary**; normally 6,500 | $60 **temporary**; normally $15 | Main coordinator, native scout, and independent reviewer. |
| Muse Spark 1.3 **xhigh** | 17% | 60% | 45,300 | $60 | Not a default for private code; see below. |
| Kimi K3 **max** | 13% | 59% | 110 | $15 | Optional, limited-budget second opinion on a difficult review. |
| GPT-5.6 Luna **xhigh** | 4% | 50% | 2,050 | $15 | Remove as default; OpenAI itself describes it as a nano-like high-volume tier. |
| Kimi K2.7 Code | 1% | 48% | 1,350 | $60 | Remove as default; the name alone did not justify choosing it. |
| Qwen3.7 Plus | 1% | 46% | 4,300 | $60 | Remove as default reviewer. |

AA comparisons supporting the quality columns: [GLM vs. DeepSeek](https://artificialanalysis.ai/models/comparisons/deepseek-v4-1-flash-vs-glm-5-3-flash),
[DeepSeek vs. Muse xhigh](https://artificialanalysis.ai/models/comparisons/deepseek-v4-1-flash-vs-muse-spark-1-3-xhigh),
[DeepSeek vs. Kimi K3](https://artificialanalysis.ai/models/comparisons/deepseek-v4-1-flash-vs-kimi-k3),
[DeepSeek vs. Luna](https://artificialanalysis.ai/models/comparisons/deepseek-v4-1-flash-vs-gpt-5-6-luna-xhigh),
[DeepSeek V4 vs. Kimi K2.7](https://artificialanalysis.ai/models/comparisons/kimi-k2-7-code-vs-deepseek-v4-flash),
and [GLM vs. Qwen](https://artificialanalysis.ai/models/comparisons/glm-5-3-flash-vs-qwen3-7-plus).
AA's Terminal-Bench is a difficult end-to-end benchmark; a 1% result does not mean a model cannot write code.
It does mean a coding label is insufficient evidence for an autonomous implementation role.

### Muse and Kimi caveats

[Meta's release](https://research.meta.ai/blog/introducing-muse-spark-1-3) reports stronger Muse 1.3 coding,
but its headline evaluations use **max** reasoning. The locally installed OpenCode Go catalog for
`muse-spark-1.3-contributor` lists variants only through **xhigh**, so the 33% Terminal-Bench result for Muse
**max** must not be attributed to the Go model by default. At xhigh, AA reports 17% on Terminal-Bench. More
importantly, [OpenCode Go's privacy table](https://opencode.ai/docs/go/#privacy) says the Contributor tier
permits Meta to train on prompts and completions. Do not silently send this project's code to it. It is a
reasonable opt-in for public/disposable code if the owner accepts that tradeoff.
The same table says DeepSeek is not used for training and has a zero-retention agreement, but that agreement
is renewed monthly and currently runs only through September 30, 2026; recheck it before sensitive work later.

Kimi K3 is a capable high-effort model, but its [Go allowance](https://opencode.ai/go) is only about 110
typical requests per five hours and 490 per month. In a multi-turn lint/review pipeline it is better reserved
for explicit, high-value second opinions than used for every edit. Its 59% SciCode result is a useful signal
for code reasoning, not a direct benchmark of reviewing FiveM resources.

### Cost interpretation

Go costs **$10/month**. The $15/$60 figures above are **included per-model usage allowances**, not separate
subscription charges; OpenCode documents 5-hour, weekly, and monthly spending windows. Request counts are
estimates based on typical token patterns, not guaranteed calls. DeepSeek pricing is peak/off-peak and the 4×
promotion is explicitly temporary. See the [Go usage details](https://opencode.ai/docs/go/#usage-limits).

## Resulting role policy

- **Coordinator:** DeepSeek V4.1 Flash, high effort — strong tool-use, fast and currently high allowance.
- **Scout:** DeepSeek V4.1 Flash, high effort — reference search is mechanically checked with `fxref`.
- **Implementer:** GLM-5.3-Flash, max effort — highest independently measured Terminal-Bench score among
  the private-code-compatible, high-allowance shortlist.
- **Reviewer:** DeepSeek V4.1 Flash, max effort — a different model family from the implementer, with ample
  requests under the current promotion. The coordinator still re-runs `fxlint` and spot-checks natives.
- **Kimi K3:** optional explicit second opinion for especially difficult or security-sensitive reviews.

This is a **benchmark-informed starting configuration**, not a claim of proven FiveM superiority. A true
decision should eventually run the same small FiveM task set through each model in this OpenCode setup and
score `fxlint`, native resolution, functional behavior, token use, and time-to-completion.
