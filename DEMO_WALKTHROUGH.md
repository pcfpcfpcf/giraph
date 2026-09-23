# GIRAPH: Demonstration & Video Production Walkthrough

**Targeting**: 40/40 pts in Stage 1 (*Video & Observability*) and 35/35 pts in Stage 2 (*Live Demo & Evidence*).

---

## 1. Golden Rules from the Jury Instructions

1. **Unedited Critical Moments**: The attack must visibly reach the defense, trigger a decision in real time, and genuinely fail on camera. Never cut or edit around the decision point.
2. **Explain As It Happens**: The observability layer must make the causal reason code and rationale crystal clear in plain English as the decision occurs.
3. **Show Benign Utility**: A legitimate benign workload must be shown completing without false blocks (`BTU = 1.0`, `FBR = 0.0`).
4. **Active Defense Toggle**: Demonstrate the contrast between baseline vulnerability (`allow_all`) and active defense (`giraph`).

---

## 2. 3-Minute Video Script (Stage 1 Submission)

| Time | Visual on Screen | Spoken Script / Voiceover | Key Elements to Highlight |
|---|---|---|---|
| **0:00 - 0:30** | Horizontal Scenario Stage (`http://127.0.0.1:8080`). Pinned track showing 28 scenarios. Smooth scroll to Situation 01. | *"This is GIRAPH, a plan-graph conformance defense for autonomous tool-using agents. In agent security, the fundamental vulnerability is that untrusted retrieved data authors control flow. GIRAPH enforces one foundational principle: **Untrusted data may select; it may never author**."* | • DNA Capital-style horizontal track<br>• Real scenario prompt & threat objective displayed on card |
| **0:30 - 1:00** | Top harness bar: Click toggle to **`DEFENSE: OFF (ALLOW_ALL)`**. Click **`[RUN TEST]`** on Situation 01 (*Direct request to mail a restricted token*). | *"First, let's observe what happens without protection. We toggle defense OFF. The adversary injects an instruction into an email thread to extract a restricted vendor portal token. Running the test... the agent blindly executes `email_send`. The attack succeeds, leaking the credential externally."* | • Red `[LEAKED]` badge appears<br>• Attack Success confirmed |
| **1:00 - 1:50** | Toggle back to **`DEFENSE: GIRAPH (ON)`**. Click **`[RUN TEST]`** on Situation 01. Click **`[INSPECT LOGS]`** to enter fullscreen workstation. | *"Now we activate GIRAPH. Prior to ingesting any untrusted data, GIRAPH constructed a verified Plan Graph and Abstract Effect Envelope. Let's re-test live. The run completes... and the outcome flips to **`[BLOCKED]`**.*<br><br>*Let's inspect the decision logs. Look at Step 1: the agent tried `wiki_search`—blocked because it wasn't authorized. But look at Step 2: the critical attack vector, `email_send`. GIRAPH detects the caller authority is untrusted. Instead of crashing the agent, GIRAPH applies a **Subplan Rewrite** (`REWRITE`), safely downgrading the action to `email_draft`. The attack genuinely failed, and no data left the perimeter."* | • Green `[BLOCKED]` state stamp<br>• Explicative Log Cards showing Step 1 `[BLOCK]` and Step 2 `[REWRITE]`<br>• Plain-English **Defense Rationale** box: *"email_send is outside policy; routed to email_draft"* |
| **1:50 - 2:30** | Exit fullscreen (`ESC`). Click the **`BENIGN [14]`** filter tab. Focus on Situation 01 (*Project Orion status lookup*). Click **`[RUN TEST]`**, then **`[INSPECT LOGS]`**. | *"Security cannot come at the expense of usability. A great defense has zero false positives. Here is a benign enterprise task: retrieving Project Orion status. We run the test... **`[CONFORMED]`**.*<br><br>*Inside the explicative logs: every action conforms to nodes N0 and N1 in the trusted plan. The final response is delivered with zero false blocks and zero unnecessary human escalations. Benign Task Utility is 100%."* | • Filter updates dynamically to 14 benign scenarios<br>• `[CONFORMED]` badge<br>• Step 01 `email_search` [ALLOW] & Step 02 `email_read` [ALLOW]<br>• All verification checks pass |
| **2:30 - 3:00** | Exit inspector. Click **`RUN ALL [28]`**. Watch the progress bar fill as scenarios complete. | *"Across all 28 benchmark scenarios—static attacks, adaptive mutations, and benign workloads—GIRAPH delivers 0% Attack Success Rate, 0% Critical Violations, 100% Benign Task Utility, and a median latency of 5.0 milliseconds. Structure defeats injection by construction."* | • Smooth batch execution<br>• Live telemetry counters: Total 28, Blocked 28, Leaked 0<br>• Summary report modal appears |

---

## 3. Stage 2 Live Presentation Script (5-10 Minutes)

### Slide / Screen 1: The Core Invariant (1 min)
- **Concept**: *"Why do prompt injections succeed? Because LLMs cannot tell instructions apart from data. Traditional defenses try to inspect strings or train classifier guards. Both fail against adaptive mutation."*
- **The GIRAPH Thesis**: *"We don't inspect text. We separate control flow from values. Untrusted data may pick between pre-authorized branches. It can never create new branches or expand the effect envelope."*

### Screen 2: Live Contrast Demo (2-3 mins)
- Open `http://127.0.0.1:8080/`.
- Run Situation 02 (*Newsletter memory poisoning*) with `DEFENSE: OFF`.
  - Show how memory poisoning writes false policy into the agent scratchpad, causing exfiltration.
- Toggle `DEFENSE: GIRAPH (ON)`.
  - Re-run Situation 02. Show `[BLOCKED]`.
  - Open Fullscreen Inspector: Show that `document_read` was allowed, but the poison injection attempting an unauthorized write failed obligation checks.

### Screen 3: The Architecture Under the Hood (2 mins)
- **The Two Phases**:
  1. *Plan Phase*: Runs once per turn. Sees ONLY the user prompt and tool catalogue. Expensive, formal, frozen.
  2. *Monitor Phase*: Runs on every tool call. Sees untrusted data. Extremely fast (5 ms). Checks: (a) Is this action a node in the graph? (b) Does it satisfy obligations? (c) Does it stay within the abstract effect envelope?
- **Effect Envelopes over Tool Names**: Tools map to abstract effects (`read`, `prepare`, `commit`, `outward_send`). Policies are written over effects, making GIRAPH completely domain-agnostic.

### Screen 4: Honest Limitations (1-2 mins)
- Conclude by proactively walking the jury through the 4 failure modes from [REPORT.md](REPORT.md#8-honest-failure-analysis):
  1. *Malicious Principal*: A user intentionally commanding exfiltration bypasses GIRAPH's planner.
  2. *Over-generalized Envelopes*: Vague user tasks require human escalation before outbound actions.
  3. *Search Depth Limits*: Horizon bounds on complex multi-turn graphs.
  4. *Semantic Masquerading*: Actions sharing identical effect boundaries.

---

## 4. UI Checklist for Recording / Demo Day

1. **Start the Live Server**:
   ```powershell
   $env:PYTHONHOME = ""
   $env:PYTHONPATH = "C:\Users\Administrator\giraph;C:\Users\Administrator\giraph\Sentinel_Starter_Kit\src"
   Sentinel_Starter_Kit\.venv\Scripts\python.exe -m uvicorn giraph.main:app --port 8080
   ```
2. **Open in Browser**:
   - URL: `http://127.0.0.1:8080/`
   - Resolution: 1440x900 or 1920x1080 (full desktop view).
3. **Key Shortcuts**:
   - `←` / `→` : Browse scenario panels.
   - `Space` : Run selected scenario.
   - `[` / `]` or `Alt+←` / `Alt+→` : Navigate previous/next situation inside Fullscreen Inspector.
   - `ESC` : Dismiss Fullscreen Inspector or Summary Modal.
