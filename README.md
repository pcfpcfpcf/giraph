# GIRAPH

**A plan-graph conformance defense for tool-using LLM agents.** Built for SENTINEL, IndabaX Tunisia 2026.

GIRAPH does not detect attacks. It verifies a plan before the agent reads any untrusted content,
then checks that every action stays inside what was verified.

> **Untrusted data may select. It may never author.**

- **Technical Report**: [REPORT.md](REPORT.md) *(Full SENTINEL Research Report & Failure Analysis)*
- **Architecture**: [ARCHITECTURE.md](ARCHITECTURE.md) *(Formal Specification & Lineage)*
- **Demo & Video Walkthrough**: [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md) *(Beat-by-Beat Video Script & Live Pitch Guide)*
- **Q&A Defense Guide**: [DEFENSE_QA_GUIDE.md](DEFENSE_QA_GUIDE.md) *(Jury Q&A Playbook for Depth Under Questioning)*

## Results (SENTINEL simulator, mock reference agent)

| Split | Attacks | Benign | ASR | BTU | CVR | FBR | UER |
|---|---|---|---|---|---|---|---|
| public | 10 | 9 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 |
| public, adaptive mutation attacker | 10 | 9 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 |
| validation | 4 | 5 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 |

Same numbers with the deterministic planner and with the Gemini planner. Reference baseline
(`provenance`): ASR 0.00, BTU 1.00, FBR 0.046.

## Layout

```
giraph/
  envelope.py        effects, authority, Envelope — the domain-free policy vocabulary
  catalogue.py       tool → effect table. The only file that names tools. Part of the TCB.
  plan.py            PlanGraph, planners (deterministic; LLM behind the same interface)
  monitor.py         conformance check: position, authority, obligations → MonitorResult
  verdict.py         MonitorResult → allow | block | escalate | rewrite
  trace.py           one JSONL record per decision
  defense.py         Giraph: plan once per (run, turn), monitor every action
  main.py            FastAPI: POST /v1/decision, GET / (observability), /graph, /trace
  sentinel_adapter.py  in-process Defense for the simulator (only file importing sentinel)
  static/index.html  observability page
tests/               unit tests + every published scenario end-to-end (in-process)
competition.yaml     simulator run config with a longer defense timeout for LLM planning
```

## Run

Requires the `Sentinel_Starter_Kit` submodule synced (`cd Sentinel_Starter_Kit && uv sync`).
GIRAPH itself needs only `fastapi`, `uvicorn`, `pydantic`, `httpx` — the kit's venv has them.

```bash
# serve the defense (deterministic planner)
Sentinel_Starter_Kit/.venv/bin/uvicorn giraph.main:app --port 8080

# run the simulator against it
cd Sentinel_Starter_Kit
uv run sentinel run  --scenario scenarios/public/finance/finance_false_approval.yaml --defense-url http://127.0.0.1:8080
uv run sentinel eval public --defense-url http://127.0.0.1:8080 --json

# observability: open http://127.0.0.1:8080/  (or load a traces/<run_id>.jsonl file offline)

# tests: 27 unit + 28 scenarios end-to-end
Sentinel_Starter_Kit/.venv/bin/python -m pytest tests -q
```

### Planner selection

| `GIRAPH_PLANNER` | Reads the request with | Extra env |
|---|---|---|
| `deterministic` (default) | verb/noun/negation rules + entity extraction | — |
| `llm` | any OpenAI-compatible local server (Ollama, llama.cpp, vLLM) | `GIRAPH_LLM_URL` (default `http://127.0.0.1:11434/v1`), `GIRAPH_LLM_MODEL` (default `qwen3:8b`) |
| `gemini` | Gemini `generateContent` | `GEMINI_API_KEY`, `GIRAPH_GEMINI_MODEL` (default `gemini-3.5-flash-lite`) |

The LLM reading is **clamped**: it may only name effect keys the catalogue defines for the task's
allowed tools, a negation found by the deterministic reading always survives, and any failure falls
back to the deterministic planner (the trace records `deterministic(fallback)`). The plan is built
inside the first decision of each task, so pass `--config ../competition.yaml` to the simulator for
a longer defense timeout when an LLM plans.

```bash
GIRAPH_PLANNER=gemini GEMINI_API_KEY=... Sentinel_Starter_Kit/.venv/bin/uvicorn giraph.main:app --port 8080
cd Sentinel_Starter_Kit && uv run sentinel eval public --defense-url http://127.0.0.1:8080 --config ../competition.yaml
```

## Running the reference agent (Qwen3-8B)

The kit's `HFModelAdapter` loads Qwen3-8B through `transformers`. On a small GPU, run the same agent
through Ollama instead: `giraph/ollama_agent.py` imports the kit adapter's system prompt, tool cards,
message layout and `parse_action`, and only replaces token generation. Nothing about *what* the
agent is changes; no safety instructions are added.

```bash
ollama pull qwen3:8b                       # Q4_K_M GGUF
# 1. vacuity check — every attack scenario must reach attack_success=True with no defense
Sentinel_Starter_Kit/.venv/bin/python scripts/run_agent.py Sentinel_Starter_Kit/scenarios/public/*/*.yaml --defense allow_all
# 2. the same scenarios against GIRAPH (in-process, or --defense http://127.0.0.1:8080)
Sentinel_Starter_Kit/.venv/bin/python scripts/run_agent.py Sentinel_Starter_Kit/scenarios/public/*/*.yaml --defense giraph
Sentinel_Starter_Kit/.venv/bin/sentinel replay artifacts/<group>/<run_id>.jsonl
```

**How we ran the reference agent:** `Qwen/Qwen3-8B` as the Ollama `qwen3:8b` Q4_K_M build, greedy
decoding (temperature 0), thinking off, 768-token decode budget, 8192-token context, 12 000-char
history window — the kit adapter's defaults except for the 4-bit quantisation and the Ollama runtime.
Results that use `--model mock` say so; the mock is the configuration the organisers verified to
inject reliably (`allow_all` reaches `attack_success=True` on 10/10 public attack scenarios).

## How a decision is made

1. **Plan** (first decision of a task; sees only `user_goal`, `policy_context`, the catalogue):
   reversible effects of allowed tools enter the envelope; irreversible ones only if the request
   asks for them and are *denied* if the request forbids them; entity IDs, amounts and email
   addresses in the request become value bindings; external destinations must be named.
2. **Monitor** (every action): is there a node for it, is its effect inside the envelope, who
   authored its selecting values (request / trusted result / agent / untrusted content / unknown),
   are the node's obligations met (bindings, confirmation, prepare-before-commit, destination,
   no confidential payload outward).
3. **Verdict**: inside + obligations met → `allow`; denied by request or outside policy → `block`;
   outside the envelope and driven by untrusted content → `block`; a reversible sub-action exists
   (send → draft, drop `status=closed`) → `rewrite`; a human could authorise it, or the checker
   returned unknown → `escalate`.

Every decision writes one trace record with the node, effect, envelope, authority evidence,
obligations checked and reason codes; the page at `/` renders the graph and the timeline per run.

## Known limits

- The deterministic planner's reading of the request is regex over verbs, nouns and negation
  scopes; the LLM planner exists because that is the weakest link. Both are clamped by policy.
- The catalogue is trusted: a mislabelled tool is a hole. It is one short table, kept auditable.
- A request that is itself out of policy is planned as asked; policy (`allowed_tools`) outranks it.
- Reads and records selected by untrusted data are allowed by design; the defense has no opinion
  on *what* is read, only on what can leave or commit.
