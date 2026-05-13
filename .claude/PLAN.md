# Meta-Investigation Plan: LLM Edge in US Equity Markets

## Goal

Answer: **"How can large language models give a retail trader a genuine, persistent edge in US equity markets?"**

Output: A list of concrete, testable trading filters/strategies, each backed by honest empirical validation.

## Success Criterion

The goal is NOT "find lots of survivors." The goal is: **eliminate bad ideas cheaply and isolate a small number of signals with real post-cost economic expectancy.** A high BROKEN rate is not failure — it means the system is working. The investigation succeeds if it produces at least one SURVIVED hypothesis with a demonstrable, executable edge, or if it conclusively demonstrates that no such edge exists within the tested space.

## Architecture: Three-Part System with Information Firewall

```
STAGE 1 (Ideation)          STAGE 2 (Pipeline)         BRIDGE (Referee)
   8 agents, 5 rounds         7 agents, 1 output        2 agents, blind
   ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
   │ 7 generative    │       │ Stats + Data +   │       │ Executor        │
   │ + 1 Skeptic     │       │ Backtest + 2x    │  ───▶ │ + Verifier      │
   │                 │       │ Breakers +       │       │                 │
   │ Internal debate │       │ Regime + Audit   │       │ Verdicts:       │
   │ → ranked list   │       │ → locked spec    │       │ SURVIVED/BROKEN/│
   └────────┬────────┘       └────────┬────────┘       │ INCONCLUSIVE    │
            │                         │                 └────────┬────────┘
            │   NEVER communicate     │                          │
            └─────────────────────────┘              Sanitized feedback
                                                          │
                                                          ▼
                                                    STAGE 1 (refine)
```

---

## Stage 1 — Idea Generation ("Creative Stage")

### Purpose
Generate novel, specific, falsifiable hypotheses about LLM-based trading edges. The agents must NOT assume any particular market inefficiency, data source, or trading horizon. They must discover edges the human designer has not considered.

### Agent Team (8 agents)

| # | Agent | Domain | Cognitive Style | Core Belief |
|---|-------|--------|-----------------|-------------|
| 1 | **Earnings Whisperer** | Earnings calls, management communications | Forensic linguist | Management teams leak truth through linguistic tells; LLMs detect these at scale no human can match |
| 2 | **Filing Archaeologist** | SEC filings, footnotes, risk factors, legal documents | Forensic accountant / legal detective | Companies structure disclosures to minimize negative interpretation; LLMs can diff filings at scale to detect meaning shifts |
| 3 | **Narrative Economist** | Media ecosystems, analyst consensus, social media narratives | Cultural anthropologist of markets | Markets oscillate between ignoring and overreacting to stories; LLMs can measure the narrative-reality gap systematically |
| 4 | **Cross-Asset Synthesizer** | CDS, bonds, options, commodities vs. equities | Systems thinker | Information arrives in one market first; LLMs can monitor multiple asset classes simultaneously to detect propagation lags |
| 5 | **Alternative Data Alchemist** | Public unconventional data: job postings, patents, FDA dockets, shipping, product reviews | Inventor / bricoleur | The world is full of free predictive data; LLMs changed the cost curve from "impossible" to "weekend project" |
| 6 | **Microstructure Mechanic** | Order flow, dealer gamma, ETF mechanics, vol surfaces, short mechanics | Engineer | Some price movements are predictable because of market structure, not information; LLMs distinguish informed from mechanical flow |
| 7 | **Behavioral Contrarian** | Positioning extremes, sentiment, short interest, consensus fragility | Systematic fader of consensus | The pain trade — what the market is most desperate to avoid — is often the one that works; LLMs identify WHEN consensus is fragile |
| 8 | **The Skeptic-in-Chief** | Adversarial — does NOT generate hypotheses | Professional paranoid | Every apparent edge is either already priced in, a statistical artifact, too small after costs, or not executable by retail. Quality control via destruction. |

### Hypothesis Template (Mandatory — All Fields Required)

For every hypothesis, each agent must complete:

```
HYPOTHESIS NAME: [Short, descriptive]
SOURCE AGENT: [Agent name]
MECHANISM: [Causal claim. "X predicts Y because Z." Specific about WHAT,
            WHAT it predicts, and WHY the relationship exists.]
LLM ADVANTAGE: [What does an LLM specifically enable here that a human
               analyst, traditional quant model, or rules-based NLP could
               not do? Scale? Linguistic subtlety? Cross-domain synthesis?]
WHY UNDERWEIGHTED: [Why isn't the market already pricing this? Too complex?
                   Too cross-domain? Too small capacity? Not on institutional
                   radar? Too expensive to process before LLMs?]
HOLDING PERIOD: [Intraday / 1-5 days / 1-4 weeks / 1-6 months / 6+ months]
DATA REQUIREMENT: [Specific data sources. Not "social media" but exactly what
                  data, from where, at what frequency, covering what period.]
PROCESSING APPROACH: [What does the LLM actually DO with the data? Classify?
                     Extract? Summarize? Compare? Generate? Embed then cluster?]
FALSIFIABLE PREDICTION: ["If this edge is real, we should observe [X]. If it
                        is fake, we would observe [Y]." Include quantitative
                        bounds where possible.]
MINIMUM EFFECT SIZE: [What is the smallest post-cost effect that would be
                     economically meaningful? E.g., "Annualized alpha > 3%
                     after costs," "Information coefficient > 0.03," "Sharpe
                     > 0.3 after costs." Below this threshold, the signal is
                     economically indistinguishable from noise even if
                     statistically significant.]
OUT-OF-SAMPLE PLAN: [How would you validate this on data you haven't looked at?]
SELF-ASSESSED CONFIDENCE: [Low / Medium / High]
BIGGEST WEAKNESS: [What are you most worried about with this hypothesis?]
```

### Interaction Protocol: 5 Rounds

**Round 1 — Divergent Discovery:**
Each generative agent (1-7) produces 2-3 hypotheses independently. No agent sees any other agent's work during this round. Total: 14-21 hypotheses.

**Round 2 — Skeptic Cross-Examination:**
The Skeptic reviews ALL hypotheses. For each: FATAL FLAW CHECK, HIDDEN ASSUMPTION, DECAY ANALYSIS, RETAIL FEASIBILITY, INITIAL VERDICT (KILL / CHALLENGE / TENTATIVE PASS). Every verdict must be justified.

**Round 3 — Collaborative Refinement:**
Open debate among all 8 agents. For each hypothesis: originating agent responds to Skeptic, other agents challenge or support from their domain, mergers proposed, revisions documented. EMERGENCE FORCING: at least one cross-agent synthesized hypothesis must be produced.

**Round 4 — Final Adversarial Review:**
Skeptic issues FINAL VERDICT on every hypothesis (KILL / REVISE / PROMOTE). PROMOTE bar is high — expected 20-40% survival rate. If more than half survive, the Skeptic has failed.

**Round 5 — Synthesis & Ranking:**
Facilitator scores all PROMOTE and REVISE hypotheses on a weighted rubric:

| Dimension | Weight | 1 = | 10 = |
|-----------|--------|-----|------|
| Edge Magnitude | 25% | Barely detectable | Transformative |
| Persistence | 25% | Days (easily arbed) | Years (structural) |
| Robustness | 15% | Fragile (dies on any spec change) | Anti-fragile (works across regimes, specs, and cost assumptions) |
| Novelty | 10% | Known factor + LLM branding | Genuinely original idea that would surprise a professional quant |
| Retail Feasibility | 10% | Requires institutional infra | Standard brokerage, sub-$250K capital, realistic time |
| Testability | 15% | Requires proprietary data | Testable with public data in <1 week |

Composite = (Edge × 0.25) + (Persistence × 0.25) + (Robustness × 0.15) + (Novelty × 0.10) + (Feasibility × 0.10) + (Testability × 0.15)

### Stage 1 Output
A ranked, scored list of PROMOTE and REVISE hypotheses, each with:
- Complete hypothesis template (all 13 fields)
- Score breakdown across all 6 dimensions
- Skeptic's final notes
- Exact data sources, time periods, and comparison group specification
- Falsifiable prediction suitable for empirical testing

---

## Stage 2 — Independent Testing Infrastructure ("Validation Stage")

### Purpose
Design and build a universal, reusable backtesting and validation pipeline capable of testing ANY hypothesis from Stage 1 — without prior knowledge of what those hypotheses will be.

### Critical Rule
Stage 2 agents NEVER see Stage 1's output. The pipeline must be designed from first principles of honest empirical research and must be general enough to test any hypothesis that involves:
- Any US equity universe
- Any time period (subject to data availability)
- Any signal that can be constructed from public data
- Any holding period from days to years

### Agent Team (7 agents)

| # | Role | Expertise & Cognitive Style |
|---|------|---------------------------|
| 1 | **Statistical Epistemologist** | Ensures statistical validity. Designs: distribution analysis, confidence intervals, multiple-comparison correction, outlier influence analysis, power calculations, bootstrap/resampling methods. The pipeline's statistical conscience. |
| 2 | **Data Engineering & Temporal Alignment Specialist** | Builds universe construction that avoids survivorship bias, look-ahead bias, and selection bias. Ensures all data is temporally aligned to the exact date when information would have been available. |
| 3 | **Backtesting & Simulation Engineer** | Designs the backtesting framework: walk-forward vs. cross-sectional, portfolio construction, position sizing, realistic transaction cost models (commissions, spread, slippage, market impact for small/micro caps, short borrow costs). Additionally: assesses retail execution feasibility — can a trader with a standard brokerage (Interactive Brokers, Schwab, etc.) actually execute this in real time? Considers: data latency, API availability, order types, position sizing relative to typical retail capital ($50K-$250K), time commitment required. |
| 4 | **Adversarial Tester — Statistical ("Statistical Breaker")** | Tries to break every result using statistical attacks: overfitting, regime dependence, parameter sensitivity, p-hacking vulnerabilities, multiple comparison traps, fragile distributional assumptions. |
| 5 | **Adversarial Tester — Data Integrity ("Data Breaker")** | Tries to break every result by attacking data integrity: survivorship bias leakage, look-ahead contamination, delisting bias, corporate action errors, stale/missing data, selection bias in control groups. Must specifically verify: (a) ticker reuse detection — ensure that when a ticker symbol is recycled by a different company years later, the database does not silently merge their histories; (b) corporate action adjustments (splits, dividends, spin-offs) are correctly applied and timestamped; (c) delisting returns are complete and sourced from available retail-accessible sources with documented biases. |
| 6 | **Regime Change & Edge Decay Specialist** | Tests whether a signal works only in specific market regimes (bull/bear, high/low vol, pre/post structural changes). Designs rolling out-of-sample validation that simulates real-time deployment. Estimates edge half-life. |
| 7 | **Reproducibility & Audit Specialist** | Ensures every test is fully reproducible — deterministic seeds, versioned data snapshots, audit trails. Designs output format so every verdict can be traced to raw data and exact code. |

### Interaction Rules
- Collaborative building, but with adversarial review at each design stage
- Either Breaker has veto power: if they can demonstrate a flaw, it must be fixed
- Pipeline design is **LOCKED** before Stage 1 output is received — no evolving methodology after seeing hypotheses
- Output: a complete, documented testing pipeline specification with implementation (code)

### Pipeline Must Address
1. **Universe construction** — survivorship-bias-free, point-in-time index constituents, delisted stocks included with delisting returns. **Mandatory retail constraint:** all data sources must be free or low-cost and accessible to a retail trader (no institutional subscriptions). Acceptable sources include: SEC EDGAR for delisting filings (Form 25, Form 15), Financial Modeling Prep free tier for delisted company reference data, Yahoo Finance or equivalent for price data. Stage 2 must evaluate and select the best available sources, and must explicitly document the known biases of each chosen source (e.g., "Yahoo Finance price data has survivorship bias for stocks delisted before 2010; mitigated by cross-referencing SEC delisting filings"). Norgate Data (~$50/month) is an optional paid upgrade for increased precision. Must source point-in-time index constituent lists (not current constituents projected backward). Must include all stocks that existed at each point in time, including those that later delisted for any reason (bankruptcy, acquisition, exchange delisting, liquidation). The Data Breaker must specifically verify these requirements are met before the pipeline is locked.
2. **Temporal alignment** — all data timestamped to when it was actually available (e.g., SEC filing acceptance date, not period end date; earnings call transcript date, not quarter end date)
3. **Control groups** — drawn from the same underlying universe, matched on relevant characteristics (size, industry, liquidity), with explicit documentation of matching methodology
4. **Transaction costs** — commissions, bid-ask spread (wider for small/micro caps), slippage estimates, short borrow costs if applicable, capacity-aware position sizing
5. **Statistical rigor** — distribution analysis (not just means), confidence intervals via bootstrap, multiple-comparison correction (Bonferroni and FDR), outlier analysis with sensitivity to winsorization thresholds, power analysis for sample size adequacy
6. **Adversarial breakage** — random permutation (shuffle signal to verify zero alpha), shuffled time periods, alternative specifications, out-of-sample holdout periods, walk-forward vs. one-shot backtest comparison
7. **Edge decay** — rolling window performance to detect decay trends, regime-conditional performance analysis
8. **Reproducibility** — deterministic random seeds, versioned data snapshots or exact source specification, complete audit trail from raw data to verdict. Must address LLM non-determinism: use small deterministic models (7B-8B parameters, temperature=0, fixed seeds) for feature extraction and structured extraction tasks. Reserve larger models only for high-level reasoning and synthesis where exact reproducibility is not required. Document which model was used for each extraction step and whether output is expected to be deterministic.
9. **Baseline factor comparison** — every hypothesis must be compared against a mandatory baseline library of known factors: momentum (12-1 month), short-term reversal (1-month), post-earnings-announcement drift, value (book-to-market), size (market cap), liquidity (Amihud illiquidity), low volatility, and sector-neutral versions of each. A hypothesis that is mostly explained by known factor exposures after costs is not a genuine LLM edge — it is factor recycling. The Bridge must report factor loadings and residual alpha after baseline factor hedging for every hypothesis tested.

### Stage 2 Output
A locked testing pipeline — either as a detailed specification (if code cannot be executed) or as executable code that can:
- Accept a hypothesis specification (data sources, signal definition, universe, time period)
- Run the full test battery automatically
- Produce verdicts with audit trails

---

## Bridge Mechanism ("The Referee + Verifier")

### Purpose
Two agents that receive Stage 1 and Stage 2 outputs and, without allowing cross-communication, apply the Stage 2 pipeline to each Stage 1 hypothesis.

### Agents

**Agent 1 — Executor:**
- Executes tests exactly as Stage 2 designed them, using the data specification from Stage 1
- Produces initial verdicts (SURVIVED / BROKEN / INCONCLUSIVE) with full audit trail
- NEVER shares Stage 2's internal reasoning or data with Stage 1
- NEVER shares Stage 1's hypotheses or reasoning with Stage 2

**Agent 2 — Verifier:**
- Independently reviews the Executor's work
- Checks: was the test applied correctly? Was the data correctly sourced and temporally aligned? Were the statistical tests run as specified?
- Can challenge the Executor's verdict if errors are found
- The two must agree before a verdict is finalized
- If they disagree, the hypothesis is marked INCONCLUSIVE with a note explaining the disagreement

### Verdicts

For each hypothesis:
- **SURVIVED:** Signal statistically significant after all corrections, economically meaningful after costs (must exceed the minimum effect size specified by the hypothesis — a signal can be statistically significant at p < 0.01 but economically zero if post-cost alpha is 0.3% with 8% volatility), robust to adversarial breakage attempts, consistent across time regimes, and not fully explained by known factor exposures after baseline comparison
- **BROKEN:** Signal fails on statistical significance, economic significance, or robustness. Specific failure mode documented.
- **INCONCLUSIVE:** Insufficient data, borderline statistical significance, or Bridge agents disagree. What additional data or specification would resolve the ambiguity is noted.
- **UNTESTABLE:** The data specified by Stage 1 is not available within the locked pipeline's data inventory (e.g., historical CDS spreads for micro-caps, FDA docket text from 2015, data from a now-defunct API). Hypothesis returned with the specific data gap identified. Does NOT count as BROKEN — the hypothesis was never tested. The Bridge must clearly document: (a) exactly which data element could not be sourced, (b) why it is unavailable, and (c) what alternative data source, if any, could make the hypothesis testable in a future iteration.

Each verdict includes a transparent audit trail of all data, code, and reasoning.

### Feedback Loop (Firewall-Preserving)
- If **BROKEN:** Bridge returns hypothesis to Stage 1 with a sanitized summary of what the test found:
  - What failed (statistical significance / economic significance / robustness / data availability)
  - Without revealing: Stage 2's methodology, exact test statistics, control group construction, or the pipeline's internal design
- If **UNTESTABLE:** Bridge returns hypothesis to Stage 1 with the specific data gap identified. Stage 1 may either (a) revise the hypothesis to use available data, (b) request a data source addition to the pipeline inventory, or (c) archive the hypothesis as "not currently testable."
- Stage 1 may refine or discard the hypothesis
- Refined hypotheses go back through the Bridge for re-testing
- If **INCONCLUSIVE:** Bridge may request additional data specification or longer time periods, communicated through sanitized channels
- Stage 2 NEVER learns which hypotheses passed or failed, preserving their blindness for future iterations

---

## Information Firewall Specification

The firewall is enforced by:
1. **Separate agent spawns** — Stage 1 and Stage 2 agents are spawned in completely separate conversations with no shared context
2. **The Bridge as sole intermediary** — no direct communication between stages under any circumstances
3. **Sanitized feedback** — the Bridge strips all Stage 2 methodology details when returning failures to Stage 1 (only "signal failed statistical significance test" not "bootstrap 95% CI was [-0.02, 0.03]")
4. **Locked pipeline** — Stage 2's pipeline is frozen before receiving any Stage 1 output; no post-hoc methodology changes
5. **No reverse flow** — Stage 1 never informs Stage 2 about which hypotheses survived or how they were refined

---

## Execution Sequence

### Phase 1: Launch Stage 1 and Stage 2 in Parallel
- Spawn Stage 1 (8 agents, 5 rounds) → produce ranked hypothesis list with full templates and score breakdowns
- Spawn Stage 2 (7 agents) → produce locked testing pipeline specification + implementation
- These run concurrently with **zero cross-communication**

### Phase 2: Bridge Application
- Spawn Bridge (Executor + Verifier) with Stage 1 output + Stage 2 pipeline
- Bridge executes tests, produces verdicts with audit trails for each hypothesis

### Phase 3: Iteration Loop
- BROKEN hypotheses loop back to Stage 1 (sanitized failure summaries only)
- Stage 1 refines or discards
- Re-test through Bridge
- Continue until surviving hypotheses are found OR Stage 1 exhausts idea space
- **Hard refinement cap:** Each hypothesis may be refined a maximum of **3 times**. After 3 submissions and 3 BROKEN verdicts, the hypothesis is permanently archived as BROKEN (exhausted). This prevents overfitting through repeated resubmission — where a hypothesis is tweaked iteratively until it accidentally fits the test data. The Bridge assigns a UUID to each hypothesis on first receipt and tracks submission counts. Stage 1 must include the UUID when resubmitting refined hypotheses so the Bridge can enforce the cap.
- **Global cap:** If an entire Stage 1 → Bridge cycle produces zero SURVIVED hypotheses after processing all non-archived hypotheses, the investigation terminates rather than looping indefinitely.

### Phase 4: Final Output
- **Section 1 — Executive Summary:** Top surviving strategies, key themes, what kind of edge the system found most promising
- **Section 2 — Surviving Strategies:** Full details for each SURVIVED hypothesis: mechanism, signal construction, expected metrics, implementation guide, risks, monitoring plan
- **Section 3 — Broken Strategies:** All BROKEN hypotheses with failure documentation (for learning and to prevent rediscovery)
- **Section 4 — Research Agenda:** What to test next, shared infrastructure to build, hypotheses that need more data
- **Section 5 — Meta-Critique:** What the system may have missed, blind spots, assumptions never challenged, how to improve the process

## Agent Count Summary

| Component | Agents | Purpose |
|-----------|--------|---------|
| Stage 1 | 8 | Hypothesis generation (7 creative + 1 adversary) |
| Stage 2 | 7 | Independent testing pipeline design + build |
| Bridge | 2 | Blind execution + verification |
| **Total** | **17** | |

---

## Known Limitations

### Human Orchestration Burden
The plan specifies separate agent spawns with no shared context. In the current environment, this requires a human operator to create separate chat sessions, paste the right inputs at the right time, and enforce the firewall manually. The Bridge agent cannot programmatically prevent cross-contamination — it can only specify the rules. **For the first run, this is acceptable.** For a fully automated loop, a scripted orchestration layer (or a single controlling agent that spawns isolated sub-agents programmatically) would be required.

### Data Inventory Scope
Stage 2's pipeline is powerful but bounded by what data is actually available. Hypotheses requiring proprietary or historical data that never existed in machine-readable form will be marked UNTESTABLE. This is a feature, not a bug — it prevents false confidence from untestable claims. But it means the system's discovery space is limited by data availability. As new data sources become accessible, the pipeline's inventory should be expanded.

### Error Cascading Risk
In multi-agent systems, a single error by one agent can propagate through the entire pipeline undetected. For example, if the Data Engineering agent incorrectly timestamps SEC filings, every subsequent verdict is contaminated. Mitigations: (a) the two-person Bridge (Executor + Verifier) catches execution errors, but does not catch errors baked into the pipeline design itself; (b) the Data Breaker's adversarial review of pipeline integrity is the primary defense. If computational resources permit, a second adversarial review of the pipeline by an independent agent (not part of the original Stage 2 team) before locking would strengthen this defense.

### Skeptic Calibration Risk
The Skeptic-in-Chief is the most critical quality gate in Stage 1, but its effectiveness depends on its "suspicion parameter." Too aggressive — it kills all viable hypotheses, including genuine alpha. Too lenient — it passes garbage that wastes the Bridge's testing resources. The plan's 20-40% PROMOTE target provides a rough calibration band, but this is a heuristic, not a guarantee. In early iterations, the Skeptic should be tuned toward lenience (so promising ideas reach the empirical test) since the Bridge provides the definitive verdict. If the Bridge consistently kills everything, the Skeptic was too lenient; if the Bridge consistently confirms everything, the Skeptic was too aggressive and valuable signals were likely killed in Round 2.
