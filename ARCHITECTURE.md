# GIRAPH — Architecture

A defense layer for tool-using LLM agents. Built for SENTINEL, IndabaX Tunisia 2026.

GIRAPH does not detect attacks. It verifies a plan before any untrusted
content is read, then checks that every action stays inside what was verified.

---

## Principle

> **Untrusted data may select. It may never author.**

Structure comes from the trusted plan. Values may come from anywhere.
Nothing untrusted can add a step, a tool, or a destination that was not
already authorized.

An injection is not blocked because it looks malicious. It is inert because
there is no channel through which it can act.

---

## Two phases

| Phase | Runs | Sees untrusted content | Cost |
|---|---|---|---|
| **Plan** | Once per task | No | Expensive |
| **Monitor** | Every turn | Yes | Cheap |

The planner runs before the agent reads anything. The monitor runs constantly
and only checks conformance against what the planner already verified.

The graph flows one way: the monitor reads it, nothing writes back.

---

## Components

### `plan.py` — Planner

Input: the user request, system policy, tool catalogue. **Nothing else.**

Output: a verified plan graph. Never mutated after creation (`frozen=True`).

The planner enumerates branches over *types*, not values. It does not know
what the invoice says. It knows a `recipient` field at
`UNTRUSTED_EXTERNAL` will arrive.

### `envelope.py` — Effect schema

Policy is written over **effects**, never over tool names.

```
read              read_credential
prepare           outward_send
commit            disable_control
```

One rule covers three domains: *untrusted authority may not drive an
irreversible outward-moving effect.* That sentence handles email
exfiltration, payment execution, and monitoring shutoff alike.

No file in this repo mentions email, payments, or incidents.

### `monitor.py` — Conformance monitor

Two questions per action:

1. Is there a graph node for it?
2. Does the action satisfy that node's obligations and stay in the envelope?

Position is necessary. Obligation satisfaction is sufficient.

### `verdict.py` — Four outcomes

| Verdict | Condition |
|---|---|
| `ALLOW` | Conforms, or diverges but stays inside the envelope |
| `BLOCK` | Needs authority the envelope never granted |
| `REWRITE` | Unsafe branch pruned, safe subplan kept (send → draft) |
| `ESCALATE` | Checker returns *unknown* — the abstraction cannot decide |

### `trace.py` — Observability

One JSONL record per decision, written live. Every record carries the node,
the obligations checked, the authority source, and the reason codes.

---

## The plan graph

```jsonc
{
  "envelope": {
    "effects":      ["read", "prepare"],
    "destinations": ["internal:draft"],
    "data_out":     [],
    "max_authority": "TRUSTED_INTERNAL"
  },
  "nodes": [
    { "id": "N2",
      "chosen_by": "DATA",
      "branches":  ["billing", "delivery", "duplicate", "unclear"],
      "obligation": "branch ∈ enumerated set" },

    { "id": "N4",
      "chosen_by": "AGENT",
      "obligation": "no credential class in draft" }
  ]
}
```

`chosen_by` is the important field.

- `AGENT` — one safe path suffices.
- `DATA` — **every** path must be safe. The adversary picks.

---

## Divergence

Real tasks leave the graph. Three cases, three responses.

| Case | Response |
|---|---|
| Predicted — a branch exists | Take it |
| Unpredicted, inside envelope | Allow, log as `ENVELOPE_CONFORMING_DIVERGENCE` |
| Needs new authority | Block, or escalate if a human could authorize |

The third case is every attack. Note that GIRAPH never has to decide whether
something *is* an attack — only whether it is outside what was verified.

### Replanning

The most attackable surface in the system. One guarded function.

- Prefer escalation.
- If automatic: replan from the original request plus **abstract** facts only
  (the routing category, never the routing email).
- A replan may only narrow the envelope. Never widen it.

---

## Trusted computing base

Three components. A bug in any one voids the guarantee.

1. **The planner** — an over-provisioned envelope lets the attack through.
2. **The effect schema** — a mislabelled tool is a hole.
3. **The replan guard** — the only path that may alter the envelope.

Keep all three small enough to read in one sitting.

---

## Known limits

- The guarantee holds only up to the search depth bound.
- A user request that is itself out of policy passes, because the plan encodes
  the request. System policy must outrank the user separately.
- Branch enumeration is only as good as the planner's imagination.
- Structural security costs utility. We report escalation rate on hard
  negatives next to block rate on attacks.

---

## Layout

```
plan.py       planner + graph schema
envelope.py   effects, destinations, data classes
monitor.py    conformance check
verdict.py    the four outcomes
trace.py      JSONL writer
main.py       POST /task/start, POST /decide
```

Per-task state: the graph, the working set with trust labels, the current node,
the effects fired so far. Nothing the agent reads may write to it.

---

## Lineage

Builds on **CaMeL** (Debenedetti et al., 2025, arXiv:2503.18813), which
established that separating trusted control flow from untrusted data defeats
injection by construction.

GIRAPH extends it in two directions CaMeL leaves open:

- **Pre-authorized branch sets** for data-dependent control flow.
- **Trajectory conformance** for multi-turn and long-horizon tasks.

Where CaMeL emits code for an interpreter, GIRAPH emits a graph for a monitor —
coarser, but cheap to build and natural to visualize.
