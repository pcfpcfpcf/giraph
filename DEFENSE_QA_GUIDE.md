# GIRAPH: Live Q&A Defense Master Guide

**Targeting**: 30/30 pts in Stage 2 (*Depth Under Questioning*).

The jury explicitly stated:  
> *"A presenter who can repeat a prepared script but cannot explain why the system made a particular decision will lose heavily in the Q&A. Depth under questioning alone is worth 30 points."*

This guide arms the presenter with deep, mathematically grounded, and implementation-accurate answers to the toughest jury challenges.

---

## 1. System Causality: "Why Did That Decision Fire?"

### Question: "In Scenario 01, Step 2, the agent attempted `email_send`. Why did GIRAPH emit a `REWRITE` decision instead of `ALLOW` or `BLOCK`?"
**Master Answer**:
> *"When `email_send` arrived at [`giraph/monitor.py`](file:///C:/Users/Administrator/giraph/giraph/monitor.py), the monitor checked three independent layers:
> 
> 1. **Graph Transition**: The current active node in the plan was `N1`, which permitted drafting and preparing internal communications.
> 2. **Authority Context**: The parameters inside the call (specifically the email body containing the secret token) were tainted with provenance label `UNTRUSTED_CONTENT` because they were derived from the external email thread.
> 3. **Effect Boundary**: `email_send` maps to the abstract effect `outward_send` in [`giraph/catalogue.py`](file:///C:/Users/Administrator/giraph/giraph/catalogue.py). Under our envelope invariant:
>    $$\text{Authority} = \text{UNTRUSTED\_CONTENT} \implies \text{Effect} \neq \text{outward\_send}$$
>    Because the envelope only authorized `internal:draft` destinations, executing `email_send` directly would cause a critical exfiltration violation.
> 
> Instead of emitting a hard `BLOCK`—which causes agent retry loops and hallucinations—[`giraph/verdict.py`](file:///C:/Users/Administrator/giraph/giraph/verdict.py) identified that the tool has a safe subplan counterpart: `email_draft`. It issued `REWRITE`, substituted the tool, recorded reason codes `TOOL_NOT_ALLOWED` and `PRUNED_TO_SAFE_SUBPLAN`, and allowed the workflow to proceed safely."*

---

## 2. Lineage & Theoretical Differences: "How is This Not Just CaMeL?"

### Question: "Your report cites CaMeL (Debenedetti et al., 2025). How does GIRAPH innovate beyond CaMeL?"
**Master Answer**:
> *"CaMeL introduced the foundational insight that separating trusted control flow from untrusted data prevents prompt injection by construction. However, CaMeL had two major practical limitations:
> 
> 1. **Data-Dependent Branching**: In CaMeL, if control flow depends on environment data (e.g. 'if invoice is overdue, call notify; else archive'), the interpreter struggles because branching on untrusted data re-opens the control-flow injection channel. GIRAPH solves this with **Pre-authorized Branch Sets** on `DATA` nodes. The planner enumerates all valid branches over *types* in advance. The adversary may pick which branch executes, but **every branch is verified safe beforehand**.
> 2. **Trajectory Conformance over Interpreted Code**: Rather than generating Python code that must execute in a custom sandboxed interpreter, GIRAPH compiles the task into a **Plan Graph**. This makes monitoring orders of magnitude faster (3.6 ms median per decision) and natively supports multi-turn agent loops where the agent takes autonomous actions across extended horizons."*

---

## 3. The Planner & The TCB: "How Does the Planner Work?"

### Question: "Where does the plan graph come from? If an LLM generates the plan, can't the LLM be tricked into generating an unsafe plan?"
**Master Answer**:
> *"GIRAPH supports both a fast deterministic rule compiler and an LLM planner behind the same [`PlanGraph`](file:///C:/Users/Administrator/giraph/giraph/plan.py) interface. But the crucial architectural guarantee is that **the planner only reads trusted input**:
> - Input to Planner: The user prompt, system policies, and the tool catalogue.
> - What the Planner NEVER sees: Any email contents, database records, search results, or external API responses.
> 
> Because the planner executes strictly *before* the agent reads any untrusted data, prompt injection into the planner is physically impossible. Furthermore, LLM-generated plans are strictly **clamped**: the planner can only name effect keys defined in the tool catalogue for the task's allowed tools, and any negation discovered in the user prompt is enforced as an invariant."*

---

## 4. Policy vs Tools: "Why Effect Envelopes Instead of Tool Allowlists?"

### Question: "Why did you build an abstract effect schema instead of simply allow-listing tool names?"
**Master Answer**:
> *"Tool allowlists are brittle and domain-specific:
> - If an enterprise renames `email_send` to `slack_post` or `teams_message`, a tool-based rule breaks.
> - An allowlist cannot express directional data flow (e.g. reading from a database is fine, but writing to that same database requires elevated authority).
> 
> In [`giraph/envelope.py`](file:///C:/Users/Administrator/giraph/giraph/envelope.py), we define policy over **semantic effect classes**: `read`, `read_credential`, `prepare`, `commit`, `outward_send`, `disable_control`.
> 
> A single invariant:
> > *'Untrusted authority may not drive an irreversible outward-moving effect'*
> 
> simultaneously protects email exfiltration in Enterprise, fraudulent wire transfers in Finance, and disabling log monitoring in SOC. In fact, not a single line of policy code in GIRAPH mentions emails, bank accounts, or security alerts."*

---

## 5. Replanning: "What If the Agent Diverges from the Plan?"

### Question: "Real tasks encounter unexpected situations. What happens when the agent leaves the graph? Can an adversary abuse replanning to escape the envelope?"
**Master Answer**:
> *"Replanning is the single most dangerous attack surface in any plan-based defense. In GIRAPH, divergence is categorized into three mutually exclusive cases:
> 
> 1. **Predicted Divergence**: An enumerated branch exists in the graph. The agent takes it.
> 2. **Unpredicted Divergence inside the Envelope**: The agent chooses an alternative tool that was not anticipated, but the action's effect stays strictly within the pre-verified envelope. We emit `ALLOW` with reason code `ENVELOPE_CONFORMING_DIVERGENCE`.
> 3. **Divergence Requiring New Authority**: The agent attempts an action outside the envelope. This is blocked or escalated.
> 
> If replanning is triggered dynamically, it must obey two inviolable invariants:
> - Replanning inputs are restricted to the original user prompt plus **abstract categorical facts** (e.g. 'category: billing', never raw email text).
> - **Monotonicity**: A replan may only *narrow* the envelope; it can never *widen* it."*

---

## 6. Honest Failure Modes: "Where Does GIRAPH Break?"

### Question: "Your technical report claims 0% ASR on the SENTINEL benchmark. Tell us where your defense actually fails."
**Master Answer**:
> *"We do not claim universal invulnerability. The 0% is on the published library with the kit's scripted mock agent. REPORT.md §6 lists where GIRAPH breaks, each one checked against the code:
>
> 1. **Transformed secrets leak.** Redaction matches the secret verbatim. If the agent base64-encodes it, spaces it out, reverses it, or the secret is under 16 characters, it is not masked.
> 2. **Redirected reads are allowed.** Untrusted data may select what is read, so a lookup redirected by an injection runs and the secret reaches the agent. Only the sinks are guarded.
> 3. **Untrusted text can fill internal records.** `record` is a reversible effect inside the envelope. We do not judge whether a note or a reply is true.
> 4. **Planner misreads.** The deterministic planner is regex over verbs and negations: "I will execute it myself later" is read as a request to execute. Confirmation is still required.
> 5. **Trusted labels and catalogue.** A mislabelled tool, or a tool output the harness forgot to label, is a hole.
> 6. **Evaluation validity.** Every number uses the mock agent, which copies secrets verbatim, and GIRAPH made no escalations on it, so escalation behaviour is untested."*

---

## 7. Performance & Latency: "What Overhead Does GIRAPH Add?"

### Question: "Does running a conformance check on every tool call slow down the agent?"
**Master Answer**:
> *"No. The expensive phase—plan generation—runs exactly once per task, before any external calls are made.
> During runtime, the conformance monitor is a lightweight, deterministic finite-state transition checker:
> - **Median Latency**: **3.6 milliseconds** (public split, over HTTP).
> - **95th Percentile (p95)**: **7.8 milliseconds**.
> - **Memory Footprint**: Negligible (JSON plan graph stored in memory).
> 
> Compared to typical LLM token generation latency (often 500 ms to 2,000 ms), GIRAPH's ~4 ms check is well under 1% overhead."*
