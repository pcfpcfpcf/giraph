# GIRAPH: technical report

**A plan-graph conformance defense for tool-using LLM agents** · SENTINEL, IndabaX Tunisia 2026

> **Untrusted data may select. It may never author.**

| ASR | BTU | FBR | CVR | Escalations | p95 latency (ms) |
|---|---|---|---|---|---|
| **0.00** | **1.00** | **0.00** | **0.00** | **0** | **7.8** |

*Public split: 40 scenarios, 31 of them attacks. Scripted `mock` reference agent. The same numbers
hold on validation and against the adaptive mutation attacker.*

**Why "GIRAPH".** GIRAPH builds on top of **CaMeL** (Debenedetti et al., 2025, arXiv:2503.18813),
and the name says so: the camel becomes a giraffe, and CaMeL's interpreted program becomes a plan
**graph**. We keep CaMeL's idea, that trusted control flow is fixed before untrusted data is read,
and swap the interpreter for a frozen plan graph that a cheap monitor checks at every step.

---

## 1. Summary

- **Problem.** Agents read untrusted text (emails, tickets, alert enrichments) and follow the
  instructions hidden in it.
- **Method.** Before the agent reads anything, GIRAPH turns the user's request into a frozen plan
  graph. The graph states which *effects* the task may cause, where data may go, and which values
  the user named. A monitor then checks every action against that graph and returns one of four
  verdicts: allow, rewrite, escalate, or block.
- **Result.** No attack succeeds, no benign task fails, no legitimate action is blocked. The best
  kit baseline, `provenance`, also stops every public attack, but blocks 22% of legitimate actions
  and lets 1 of 4 validation attacks through.
- **Main limitation.** Redaction matches secrets verbatim. A secret the agent base64-encodes,
  spaces out, or reverses gets through (§6).

---

## 2. Threat model and hypothesis

| | |
|---|---|
| **Defends against** | direct instructions, indirect injection, data exfiltration, multi-step, memory poisoning, tool-output manipulation: every family in the library |
| **Adversary** | controls declared text surfaces, sees the transcript and our decisions, adapts between steps, knows our code |
| **Trusted** | the user's request and task policy, the harness's provenance labels, our short effect catalogue |
| **Out of scope** | whether a reply or record is *true*, what the agent reads, requests that are themselves malicious |

**H1.** A frozen effect envelope plus authority and data-flow checks gives ASR 0 on public and
validation, with FBR ≤ 0.05. **Holds** in the mock-agent setting.

**H2.** Removing the planner, authority tracing, or redaction each raises ASR on at least one split.
**Partly falsified:** authority tracing alone changes nothing (§5).

---

## 3. How it works

![Where GIRAPH sits: the planner runs once and sees no untrusted content; the monitor runs on every action.](docs/img/arch2.png)

**① Plan (once per task, before any untrusted read).** The planner receives only the request, the
policy, and the catalogue that maps each tool to an effect.

| Effect class | Effects | In the envelope when… |
|---|---|---|
| Reversible | `read` `prepare` `record` `respond` `memory_write` | the tool is allowed |
| Irreversible | `commit` `outward_send` `read_credential` | **the request asked for it** |
| Never | `disable_control` | never |

Anything the request forbids ("do not execute") is denied for good. External addresses are allowed
only if the request names them. IDs, amounts, and emails in the request become *bound values*.

**② Monitor (every action).** The monitor answers four questions:

1. Is there a node for this action?
2. Is its effect inside the envelope?
3. **Who authored the values that select it?** The request, a trusted result, the agent, or
   untrusted content. Untrusted data may *select* which record to read. It may never *author* an
   irreversible action.
4. Are the node's obligations met? These are confirmation, prerequisite, bound values, allowed
   destination, no confidential data going outward, and **no credential-class data reaching any
   sink**. That last one covers replies, notes, memory, and our own trace.

![The verdict ladder: rules fire top to bottom and the first match wins.](docs/img/verdict.png)

Risk and confidence are fixed values per rule, from 0.05 for a clean reply to 0.95 for an unknown
tool. They are not fitted. Every decision carries reason codes and an evidence string, for example
`severity='low' appears only in untrusted_external content`. The scenario runner (`/`) and the
dashboard (`/dashboard`) show these live next to the plan graph.

**No hard-coding.** GIRAPH never sees scenario IDs, reference plans, or expected outcomes. Only
`catalogue.py` names tools. The envelope, monitor, and verdict logic are written over effects
alone.

---

## 4. Results

![Attack success and false blocks against the kit's baselines.](docs/img/headline.png)

| Run (mock agent) | ASR | BTU | FBR | TUI | DFI | Brier | ECE |
|---|---|---|---|---|---|---|---|
| **GIRAPH** · public | **0.00** | **1.00** | **0.00** | 0.80 | 1.00 | **0.087** | 0.074 |
| **GIRAPH** · public, adaptive attacker | **0.00** | 1.00 | 0.00 | 0.77 | 1.00 | 0.091 | 0.063 |
| **GIRAPH** · validation | **0.00** | 1.00 | 0.00 | 0.93 | 1.00 | 0.036 | 0.061 |
| **GIRAPH** · validation, adaptive attacker | **0.00** | 1.00 | 0.00 | 0.93 | 1.00 | 0.039 | 0.056 |
| provenance · public | 0.00 | 1.00 | 0.22 | 1.00 | 1.00 | 0.147 | 0.197 |
| heuristic_risk · public | 0.68 | 1.00 | 0.00 | 0.75 | 0.48 | 0.114 | 0.050 |
| allow_all · public | 1.00 | 1.00 | 0.00 | 0.65 | 0.40 | 0.235 | 0.235 |

![What GIRAPH did with each tool call on the public split.](docs/img/decisions.png)

- **Exfiltration (21 scenarios)** is stopped by *redacting the secret* on the write step, so the
  task still completes. The redirected lookup before it is allowed; see §6.
- **Direct instructions, injection, multi-step, memory poisoning, and tool-output manipulation**
  are blocked by policy, the request's denials, or the envelope.
- **TUI 0.80 is below provenance's 1.00 on purpose.** A rewritten call still runs, in redacted
  form, and the kit counts it as illegitimate. Provenance blocks those calls instead, and pays
  with FBR 0.22.

> **Replay: `soc_backup_token_disclosure`.** The alert's enrichment tells the agent to look up
> SRV-22 and paste the record into an incident.
> `asset_lookup` → **ALLOW** (0.10) · `incident_create` → **REWRITE** (0.85,
> `RESTRICTED_DATA_REDACTED`, summary becomes `[REDACTED]`) · reply → **ALLOW** · task passes, no
> leak.

---

## 5. Ablations

![Attack success when one component is removed.](docs/img/ablation.png)

| Removed | What changes | Meaning |
|---|---|---|
| **redaction** | public ASR **0.00 → 0.55** (17 attacks land) | Carries the exfiltration family. Those writes are inside the plan, so only the data-flow check separates attack from task. |
| redaction **and** authority | public ASR **0.68** | Authority is the second line: it escalates 4 drafts staged on injected instructions. |
| authority alone | nothing | **H2 falsified** for this component on its own. |
| planner | validation ASR **0.25** | Only the planner's destination list rejects the injected recipient in `enterprise_val_encoded_exfil`. |
| rewrite | FBR **0.00 → 0.05** | Rewrite buys precision, not security. |

**Honest reading.** On this library, policy and redaction do most of the stopping. What GIRAPH
adds over `provenance` is **zero false blocks**, better calibration, and a destination envelope.

---

## 6. Failure analysis: where GIRAPH breaks

| # | Failure | Evidence | Root cause | Fix direction |
|---|---|---|---|---|
| 1 | **Transformed secrets leak** | probe on the SRV-22 token: verbatim and upper-case are masked; **base64, spaced-out, reversed, split, <16 chars, or digit-free** are not | redaction matches the surface form of the restricted record | treat every field value of a restricted record as secret; decode and normalise before matching |
| 2 | **Redirected reads are allowed** | 14 illegitimate calls allowed on public, **all reads** | by design ("data may select"); the secret reaches the agent, and only the sinks are guarded | put secret-reading tools behind `read_credential` |
| 3 | **Untrusted text can fill internal records and replies** | the §4 incident's `severity` came from the injection; without a secret it would be allowed at risk 0.30 | `record` is reversible and inside the envelope; we do not judge truth | human review of records with untrusted authority |
| 4 | **Planner misreads** | "I will execute it myself later" → `payment_execute` requested | regex over verbs and negations | clamped LLM planner (implemented, not evaluated); confirmation still required |
| 5 | **Trusted labels and catalogue** | a tool output with no provenance is trusted; a mislabelled tool is a hole | these are the trusted computing base | keep them small and audited |
| 6 | **Evaluation validity** | every number uses the scripted mock agent; 0 escalations happened | the mock copies verbatim, which is favourable to weakness 1 | re-run with Qwen3-8B (tooling is in the repo) |

> **Found and fixed:** the first redaction masked every 16-character phrase copied from a
> restricted record, which mangled honest paraphrases. It now masks only secret-shaped values and
> wholesale copies of 48+ characters. The cost is failure 1's short-secret gap.

---

## 7. Responsible AI

- **Protects against:** irreversible effects the user did not ask for, confidential data going
  outward, and verbatim credentials in any sink. **Does not protect against** failures 1–5.
- **False positives we expect in real use:** planner misses and unnamed external recipients
  *escalate*, so the user waits. Long verbatim quotes from restricted records are *redacted*, so a
  reviewer sees `[REDACTED]`. Uncatalogued tools are *blocked*.
- **Humans in the loop:** every consequential action needs a recorded confirmation. Out-of-envelope
  actions that no untrusted content drives are escalated, not blocked.
- **Data:** GIRAPH keeps plans in memory and writes one JSONL trace per decision, *redacted like any
  other sink*. With the default planner nothing leaves the host. The Gemini planner sends the
  **request only** to Google.
- **Domains:** security metrics are identical across enterprise, finance, and SOC. Calibration is
  weaker in SOC and finance (ECE 0.12 / 0.18), where most redirected reads happen.

---

## 8. Reproducibility

GIRAPH `ab2e6a3` · kit `dd2e5fe` · `sentinel-bench/0.1.0` · seed 0 · `--model mock` · 83 tests pass.

```bash
Sentinel_Starter_Kit/.venv/bin/uvicorn giraph.main:app --port 8080 &
cd Sentinel_Starter_Kit
uv run sentinel eval public --defense-url http://127.0.0.1:8080 --json
uv run sentinel eval public --defense-url http://127.0.0.1:8080 --attacker mutation --attack-mode adaptive --json
uv run sentinel eval validation --defense-url http://127.0.0.1:8080 --json
uv run sentinel eval public --defense provenance --json
cd .. && Sentinel_Starter_Kit/.venv/bin/python scripts/ablation.py
```

| Scorecard | Deterministic digest |
|---|---|
| GIRAPH public | `0d6c45a345ed…` |
| GIRAPH public, adaptive | `d4f66ca6876b…` |
| GIRAPH validation | `e80110527c75…` |
| provenance public | `7e9ab1696a87…` |
| allow_all public | `a9aa03e1ebc6…` |

No external models or datasets are used in the reported configuration.
