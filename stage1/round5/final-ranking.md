# Stage 1, Round 5: Final Synthesis, Scoring, and Ranking

**Role:** Facilitator — Synthesis and Ranking
**Date:** 2026-05-13
**Round:** 5 of 5 — FINAL
**Purpose:** Score all surviving hypotheses on the 6-dimension weighted rubric, rank by composite score, and produce the Stage 1 synthesis.

---

## 1. EXECUTIVE SUMMARY

### Scope

This document scores **16 hypotheses** — 6 PROMOTE and 10 REVISE — that survived Round 4 adversarial review. Six KILLED hypotheses are scored in an appendix on a "what-if" basis (the score they would have received if their fatal flaw were magically fixed), to inform future research direction.

### Score Distribution

- **Highest composite score:** 8.30 — A5-H1 (FDA Briefing Document Asymmetric Skepticism)
- **Lowest composite score (surviving):** 3.50 — A4-H3-Revised (Post-FOMC Factor Regime Classification)
- **Mean surviving score:** 5.65
- **Median surviving score:** 5.80
- **PROMOTE mean:** 7.32
- **REVISE mean:** 4.96
- **Standard deviation (all surviving):** 1.46

### Score Range by Dimension

| Dimension | Weight | Range (Surviving) | Mean (Surviving) |
|-----------|--------|-------------------|-------------------|
| Edge Magnitude | 25% | 3-8 | 5.1 |
| Persistence | 25% | 2-9 | 5.8 |
| Robustness | 15% | 3-8 | 4.8 |
| Novelty | 10% | 4-10 | 6.8 |
| Retail Feasibility | 10% | 2-10 | 6.1 |
| Testability | 15% | 4-9 | 5.9 |

### Key Thematic Findings

1. **Regulatory and auditor signals dominate the top tier.** FDA briefing document linguistic asymmetry (A5-H1, 8.30) and CAM expansion velocity (A2-H2, 7.40) both extract predictive signals from institutional gatekeepers — FDA reviewers and external auditors — whose assessments are mandatory, public, and systematically under-parsed by the market. These are the strongest hypotheses because they combine structural durability, free archival data, and a genuine LLM measurement advantage.

2. **Linguistic measurement at scale is the strongest unifying capability.** Across the top-ranked hypotheses, the LLM's unique contribution is not sentiment analysis or text classification in the generic sense, but specific, fine-grained linguistic measurements that no existing system can perform: per-executive pronoun baselines (A1-H1), statement-to-actual credibility tracking (A3-H3), benefit-risk hedging asymmetry (A5-H1), and cross-stage consensus fragility (ACF). These are measurement tasks, not classification tasks — they require computing structured quantities from unstructured text at a scale and precision that only LLMs enable.

3. **Negative screening outperforms directional betting as a strategy template.** The departure language severity hypothesis (A2-H3, 7.25) survived by rescoping from a directional short strategy (80-90% false positive rate, death by negative carry) to a negative screening tool (avoid these stocks, reduce blowups by 40%). This pattern — signals with moderate predictive power deployed as portfolio screens rather than directional bets — is a recurring lesson. Several REVISE hypotheses could benefit from the same reframing.

4. **The "Wisdom of the Amateur" fallacy is the single most common killer.** Hypotheses that assumed a retail trader could compete with institutional participants at their own game — front-running options market makers (A6-H1, KILLED), capturing ETF creation flow with T+1 data (A6-H3, KILLED), or exploiting commodity-equity propagation delays (A4-H2, KILLED) — were uniformly killed. The LLM's measurement advantage does not compensate for structural disadvantages in data timeliness and execution speed.

5. **Data accessibility is the binding constraint for retail strategy design.** The CDS-Transcript Divergence hypothesis (CTDS, 6.15) is arguably the most intellectually novel idea in the entire set — it could only emerge from the intersection of three agents' domains — but its retail feasibility is crippled by the CDS data paywall. The Analyst Consensus Fragility hypothesis (ACF, 7.10) partially degrades if free analyst snippet quality is poor. The most successful hypotheses (FDA, CAM, Departure Language, Pronoun Divergence, Credibility Trajectory) all use data that is not only free but archival — available historically for backtesting without vendor dependency.

6. **Emergence from multi-agent interaction is real but rare.** The merged ACF hypothesis (7.10) genuinely improves on its parent hypotheses by measuring consensus fragility at two points in the earnings cycle. The synthesized CTDS hypothesis (6.15) is a truly emergent idea that no single agent could have conceived. However, most cross-agent interactions produced incremental improvements (shared infrastructure, combined signals) rather than genuinely new hypotheses — the bar for emergence is high.

---

## 2. RANKED TABLE WITH ALL DIMENSION SCORES

### Composite Score Formula

**Composite = (Edge x 0.25) + (Persistence x 0.25) + (Robustness x 0.15) + (Novelty x 0.10) + (Feasibility x 0.10) + (Testability x 0.15)**

### Full Ranking (All Surviving Hypotheses)

| Rank | Hypothesis | Verdict | Edge (25%) | Persist (25%) | Robust (15%) | Novelty (10%) | Feasibility (10%) | Testability (15%) | **Composite** |
|------|-----------|---------|------------|---------------|-------------|---------------|------------------|-------------------|---------------|
| 1 | A5-H1: FDA Briefing Document Asymmetric Skepticism | PROMOTE | 8 | 9 | 8 | 8 | 7 | 9 | **8.30** |
| 2 | A2-H2: CAM Expansion Velocity as Distress Precursor | PROMOTE | 5 | 9 | 7 | 9 | 9 | 7 | **7.40** |
| 3 | A2-H3: Departure Language Severity (Screening Tool) | PROMOTE | 5 | 9 | 6 | 8 | 10 | 7 | **7.25** |
| 4 | A1-H1: Pronoun Divergence Signal | PROMOTE | 6 | 8 | 6 | 7 | 8 | 8 | **7.10** |
| 5 | ACF: Analyst Consensus Fragility (Merged) | PROMOTE | 7 | 7 | 7 | 8 | 7 | 7 | **7.10** |
| 6 | A3-H3: Management Credibility Trajectory | PROMOTE | 6 | 8 | 6 | 6 | 7 | 7 | **6.75** |
| 7 | A5-H3: App Store Review Functional Failure | REVISE | 5 | 7 | 5 | 8 | 7 | 6 | **6.15** |
| 8 | CTDS: CDS-Transcript Divergence Signal | REVISE | 7 | 8 | 3 | 10 | 2 | 5 | **6.15** |
| 9 | A1-H2: Scripted-Answer Echo Detection | REVISE | 5 | 7 | 4 | 6 | 7 | 6 | **5.80** |
| 10 | A3-H1: Q&A Coherence Decay (QACD) | REVISE | 5 | 5 | 5 | 7 | 6 | 6 | **5.45** |
| 11 | A2-H1: Risk Factor Clean vs. Dirty Removal Drift | REVISE | 4 | 6 | 3 | 7 | 6 | 6 | **5.15** |
| 12 | A6-H2: Pre-Earnings Abnormal Short Flow | REVISE | 5 | 5 | 3 | 5 | 5 | 5 | **4.70** |
| 13 | A5-H2: Job Posting Semantic Pivot | REVISE | 5 | 4 | 4 | 8 | 3 | 4 | **4.55** |
| 14 | A7-H3: Retail Options Flow Exhaustion | REVISE | 4 | 4 | 4 | 6 | 5 | 5 | **4.45** |
| 15 | A4-H1: Supply Chain Shock Transmission | REVISE | 3 | 3 | 3 | 5 | 5 | 5 | **3.70** |
| 16 | A4-H3-Revised: Post-FOMC Factor Regime | REVISE | 3 | 2 | 3 | 4 | 8 | 4 | **3.50** |

### Ranked by Dimension (Top 3)

| Dimension | 1st | 2nd | 3rd |
|-----------|-----|-----|-----|
| Edge Magnitude | A5-H1 (8) | ACF (7) | CTDS (7) |
| Persistence | A5-H1 (9) | A2-H2 (9) | A2-H3 (9) |
| Robustness | A5-H1 (8) | A2-H2 (7) | ACF (7) |
| Novelty | CTDS (10) | A2-H2 (9) | A5-H1 / A5-H3 / ACF / A2-H3 (8) |
| Retail Feasibility | A2-H3 (10) | A2-H2 (9) | A1-H1 / A4-H3-R (8) |
| Testability | A5-H1 (9) | A1-H1 (8) | 6 hypotheses at 7 |

---

## 3. PER-HYPOTHESIS DETAILED SCORING CARDS

---

### RANK 1: A5-H1 — FDA Briefing Document Asymmetric Skepticism

**Verdict:** PROMOTE
**Agent:** Alternative Data Alchemist (Agent 5)
**Composite:** 8.30

**Mechanism (one sentence):** FDA reviewers encode skepticism through asymmetric hedging — hedging benefit claims with cautious language while stating safety concerns with definitive language — predicting Complete Response Letters at 2.5-3x the unconditional rate, 1-5 days before the formal FDA decision.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 8 | 2.5-3x lift in CRL probability (from 15-20% to 50%) on binary biotech events with -30% to -70% single-day crash potential. Avoiding 1 in 3 CRLs saves 200-300bps of portfolio value annually. The edge is very large per-event, though the opportunity set is limited to 150-200 PDUFA drugs/year. |
| Persistence | 9 | FDA documents are dense (50-200 pages), domain-specific (medical/statistical/regulatory), and require cross-document baseline comparison at scale that no systematic market participant performs. Per-reviewer normalization adds another processing layer. The universe is naturally limited, deterring institutional capital allocation. Decay horizon: 5-10+ years. |
| Robustness | 8 | Data is from a single source (FDA) with consistent document formats and fully archival records. Per-reviewer normalization (where documents are signed, ~60-70% of cases) controls for individual writing style rather than just division-level norms. The "too clean" problem (drugs reaching adcom are already triaged) is a constraint on the universe, not a flaw in the signal mechanism. Works on both adcom and non-adcom PDUFAs. |
| Novelty | 8 | Academic research on FDA regulatory linguistics exists (Batta et al., Lexchin & Mintzes) but has never been operationalized into a pre-decision predictive trading model. The BRLAS measurement is genuinely novel — no one computes cross-sectional linguistic asymmetry scores across all drugs under review. The individual building blocks (hedging density, certainty markers) exist in the linguistics literature, but the specific composite and its application to FDA decision prediction is original. |
| Retail Feasibility | 7 | All data is completely free and archival (fda.gov). Briefing documents are published on a deterministic schedule (typically 2 business days before adcom). The 1-5 day holding period is ideal for retail execution. Put options provide defined-risk short exposure. The main barrier is domain knowledge: correctly understanding FDA document structure and drug review processes requires familiarity with regulatory medicine that most retail traders lack. The LLM handles the linguistic measurement, but the trader must understand the output context. |
| Testability | 9 | This is the most testable hypothesis in the entire set. Data is fully archival back to at least 2017. Outcomes are binary (CRL vs. approval) with objective, publicly verifiable ground truth. The falsifiable prediction (2.5-3x lift in CRL probability) is specific and quantitative. Multiple FDA review divisions provide natural cross-validation subsets. The Phase 1 calibration only requires downloading and processing historical documents — no expensive API calls, no web scraping, no data vendor dependencies. |

**Key Risks:**
- Option market efficiency: pre-PDUFA implied volatility is 150-300%. The options-implied probability benchmark must confirm BRLAS adds incremental predictive power beyond what option prices already reflect.
- Reviewer heterogeneity: even within-reviewer normalization requires sufficient reviewer-specific document history to establish baselines.

---

### RANK 2: A2-H2 — CAM Expansion Velocity as Distress Precursor

**Verdict:** PROMOTE
**Agent:** Filing Archaeologist (Agent 2)
**Composite:** 7.40

**Mechanism (one sentence):** When auditors add Critical Audit Matters in new topic clusters not previously associated with a company, it signals escalating accounting complexity that precedes visible financial deterioration by 1-3 quarters — auditor-identified problems the market has not yet priced.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | Annualized alpha >5% over 6-month holding period. The structural lag (auditors identify problems 45-90 days after fiscal year-end, and 1-2 earnings releases occur before the 10-K is filed) means some deterioration is already priced. The critical test — whether CAM expansion predicts returns even when recent earnings are stable — will determine if the edge is additive or redundant. Moderate edge, not transformative. |
| Persistence | 9 | CAMs are mandatory, standardized disclosures (PCAOB AS 3101) that almost no quant fund systematically processes. The dataset is young (since mid-2019), so no mature strategy exists. CAM topic clustering across the entire market requires embedding + clustering infrastructure that represents a genuine barrier to entry. Academic literature is thin and focused on audit fees, not stock returns. Decay horizon: 5+ years. |
| Robustness | 7 | CAMs are a regulatory mandate — not dependent on any single data vendor. The event-study methodology (replacing quintile sorts) resolves the power concern from Round 2. However, the auditor-timeliness test may reduce the effective sample to a subset where effects are harder to estimate precisely. CAM language varies by audit firm (Deloitte vs. PwC vs. EY vs. KPMG), requiring robust embedding models that generalize across firm-specific language. |
| Novelty | 9 | CAM topic clustering across the entire market is a genuinely novel measurement that no existing commercial data product performs. The CAM expansion velocity metric — how many NEW topic clusters the auditor has added — is an original quantification of an auditor's escalating concern. The market views the auditor's report as a binary pass/fail signal; treating it as a continuous, multi-dimensional signal source is a genuinely new approach. |
| Retail Feasibility | 9 | All data is free (SEC EDGAR). Processing is quarterly batch — not daily scanning. LLM costs are $30-90/quarter for CAM extraction and clustering across 3,000+ filings. The 1-6 month holding period requires patience but minimal trading activity. No short-selling required for the long-short version. Among the lowest time-and-cost commitments of any hypothesis. |
| Testability | 7 | Data available 2019-present (6+ years). Pooled event study with 1,800-5,400 company-event observations provides adequate statistical power. Fama-French 5-factor + momentum benchmark controls for known factors. The stable-earnings subset test is dispositive. However, 6 years is still a limited time series for a 6-month holding period, and overlapping observations require appropriate standard error adjustments. |

**Key Risks:**
- Auditor timeliness: even with the stable-earnings test, the structural lag means the CAM signal must provide incremental information beyond what the market can already observe from quarterly earnings releases.
- Limited history: 6 years of data means rare CAM expansion types (e.g., going concern CAMs) have very few observations.

---

### RANK 3: A2-H3 — 8-K Departure Language Severity as Stealth Warning (Screening Tool)

**Verdict:** PROMOTE
**Agent:** Filing Archaeologist (Agent 2)
**Composite:** 7.25

**Mechanism (one sentence):** The linguistic severity gradient in 8-K officer departure filings — suddenness, perfunctory farewells, investigation co-occurrence — identifies stocks with disproportionate blowup risk (3.5x concentration in top decile), serving as a negative screen that avoids 40% of -30%+ single-stock events.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | As a screening tool (not a directional trade), the economic value is in risk reduction rather than alpha generation: 200bps max drawdown reduction over 3 years, 40% fewer -30%+ single-stock events, Sortino ratio improvement of 0.10. Economically meaningful for a long-only portfolio but not a source of positive return. The edge magnitude is moderate because most flagged stocks do NOT blow up — the signal avoids rare but catastrophic events. |
| Persistence | 9 | The linguistic severity gradient is genuinely unmeasured by any existing data product. Downweighting CEO/CFO features (which the market already efficiently processes) and upweighting language features (thank-you length, suddenness, investigation co-occurrence) makes the signal orthogonal to known effects. As a negative screen, there is no alpha to arb away — it's a risk management tool. Indefinite persistence as a screening methodology. |
| Robustness | 6 | Selection bias is the primary robustness concern: companies in the most extreme distress (fraud, imminent bankruptcy) may not file clean Item 5.02 8-Ks at all, or may file them late. The signal captures the "gray zone" — distressed but compliant companies — and may miss the true black swans. Additionally, different law firms draft departure 8-Ks with different linguistic conventions, introducing a confound. |
| Novelty | 8 | The fine-grained linguistic gradient within departure filings — the "warmth of farewell" measurement, the suddenness-vs-planned distinction, the investigation co-occurrence flag — is genuinely novel. The rescoping from directional short to negative screening tool is itself a methodological innovation: recognizing that moderate-precision signals are better deployed as screens than as trades. |
| Retail Feasibility | 10 | The most feasible hypothesis in the entire set. All data is free (SEC EDGAR 8-Ks). As a screening tool, execution is simply "don't buy flagged stocks" or "sell existing positions in flagged stocks." No short-selling. No options. No margin. No specific entry/exit timing beyond "check quarterly." The LLM extraction and classification pipeline is a batch process. A retail trader with $50K can implement this by checking a list once per quarter before rebalancing. |
| Testability | 7 | Requires measuring subsequent adverse events (restatements, material weaknesses, SEC investigations, -50%+ crashes) over 12-month horizons. The 3.5x concentration claim is a specific, testable prediction. Incident rate analysis across deciles is straightforward. However, adverse event identification requires careful data collection (not all blowups have clean labels), and the selection bias concern (worst cases don't file) limits the maximum observable effect. |

**Key Risks:**
- Selection bias: companies in the most extreme distress may not file clean 8-Ks, limiting the signal's extreme-tail capture.
- The 3.5x concentration claim should be verified against a list of known historical blowups to measure how many had detectable high-severity departure filings beforehand.

---

### RANK 4: A1-H1 — The Pronoun Divergence Signal

**Verdict:** PROMOTE
**Agent:** Earnings Whisperer (Agent 1)
**Composite:** 7.10

**Mechanism (one sentence):** Executives unconsciously shift from first-person plural ("we," "us," "our") to depersonalized constructions during Q&A when they possess undisclosed negative information or face material uncertainty, predicting negative excess returns of 200bps over 1-5 days.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 6 | Predicted effect of 200bps excess negative return over 5 days, net of 50bps transaction costs. Substantial for a 5-day tactical hold. However, the signal only fires after earnings calls (quarterly per stock) and only for the fraction of calls where the executive shows significant pronoun divergence. The per-trade edge is meaningful but the annualized opportunity set is constrained by the quarterly firing frequency. |
| Persistence | 8 | Behavioral signals embedded in unconscious speech patterns are among the hardest to arbitrage away — executives cannot easily control their pronoun usage, and the signal generators are unaware they are generating a signal. Per-executive baseline modeling over 8+ quarters creates a substantial barrier to replication. The mechanism is grounded in psycholinguistics literature that has existed for decades without being operationalized into a trading factor. Decay horizon: 3-5+ years. |
| Robustness | 6 | The mechanism was broadened from "concealment" to "uncertainty or concealment," which makes it more robust across scenarios — both hiding bad news and genuinely struggling with uncertain conditions predict negative drift. The transcript fidelity pre-filter (verify >=5 first-person plural pronouns in Q&A before processing) is a practical, zero-cost gate. However, the signal remains dependent on transcript quality — if EDGAR-filed transcripts are subtly paraphrased (pronouns preserved but sentences restructured), the PPR metric may be contaminated without the pre-filter catching it. |
| Novelty | 7 | The academic literature on pronoun shifting and deception is well-established (Pennebaker, Larcker & Zakolyukina, Hobson et al.), but it has never been operationalized into a systematic, daily-actionable trading factor. The specific application — per-executive baselines on earnings call Q&A, with topic-level segmentation and asymmetric prediction (drops predict negative, spikes do NOT predict positive) — is a genuinely novel operationalization of known psycholinguistic effects. Not a new discovery, but a new implementation. |
| Retail Feasibility | 8 | All data is free (SEC EDGAR transcripts, Seeking Alpha, Yahoo Finance). The LLM pipeline runs overnight post-market after earnings calls are released (typically by 6pm ET). 1-5 day holding period allows end-of-day execution. LLM API costs at $120-360/quarter are within budget. Short exposure via inverse ETFs or put options avoids margin requirements. The main friction is short-selling access for a retail account, but the agent correctly identifies workarounds. |
| Testability | 8 | Specific, falsifiable prediction: flagged stocks should exhibit negative excess returns of at least 200bps over 5 days, with asymmetry (pronoun drops predict negative, spikes do NOT predict positive). Data is archival back to at least 2010. Per-executive baselines require 8+ quarters of history, which is available for most actively traded companies. The out-of-sample plan (train 2021-2023, validate Q1-Q3 2024, test Q4 2024-Q1 2025) is well-structured. The main testing challenge is the transcript fidelity validation against audio recordings. |

**Key Risks:**
- Transcript paraphrasing: even EDGAR-filed transcripts may be subtly cleaned, and the pre-filter (5+ pronouns) won't catch paraphrasing that preserves pronouns but changes sentence structure.
- Phase 1 manual validation against audio recordings is essential before committing capital.

---

### RANK 5: ACF — Analyst Consensus Fragility (Merged)

**Verdict:** PROMOTE
**Agents:** Narrative Economist (Agent 3) + Behavioral Contrarian (Agent 7)
**Composite:** 7.10

**Mechanism (one sentence):** When pre-earnings analyst arguments AND during-call analyst questions both show extreme semantic homogeneity, with no post-call estimate revision, the consensus is an information cascade — and the stock reverses opposite the consensus direction over 1-4 weeks.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 7 | Predicted hit rate >60% with mean reversal magnitude >4% over 20 trading days. Long-short Sharpe >0.5. The edge is in fading fragile consensus — both long opportunities (fading bearish consensus) and short opportunities (fading bullish consensus). The post-call estimate revision filter (fewer than 2 analysts revise) distinguishes fragile from warranted consensus, which should meaningfully improve precision over either parent hypothesis alone. |
| Persistence | 7 | Convergent measurement across two time points and two data sources provides mutual validation that is harder to replicate than either single-source signal. The cross-stage theme matching (consistent vs. inconsistent) is a genuinely novel methodological step. However, analyst consensus measurement is a well-studied area, and the component signals (argument similarity, question similarity) could be replicated individually. The joint conditioning provides a moat, but not an insurmountable one. Decay horizon: 3-5 years. |
| Robustness | 7 | Graceful degradation is a built-in strength: if free analyst snippet quality is poor, the ACF degrades to the QHS-only version (during-call question homogeneity), which uses full transcripts and is unaffected by snippet quality. The post-call estimate revision filter is a strong discriminator between fragile and warranted consensus. The signal requires at least 5 analysts covering the stock, limiting the universe to mid-to-large caps where consensus dynamics are stronger but competition is fiercer. |
| Novelty | 8 | The joint conditioning — pre-call AND during-call AND cross-stage theme matching AND post-call revision filter — is genuinely novel. Neither parent hypothesis could achieve this alone. The insight that consensus fragility must be measured at BOTH points in the earnings cycle (before the call establishes the thesis; during the call probes whether it survives) is something neither single agent would have produced. The merger genuinely adds value beyond the sum of its parts. |
| Retail Feasibility | 7 | All data sources are free/freemium. The long-side priority (fading bearish consensus = buying) avoids short-sale constraints, which is the biggest practical improvement over the parent hypotheses. 1-4 week holding period is manageable. The main concern is the free analyst snippet quality gate — if pre-call snippets lack sufficient detail for argument diversity measurement, the merged value proposition weakens (though the during-call component survives independently). |
| Testability | 7 | Requires both pre-call analyst commentary (free snippets) and during-call transcripts (full text). Long historical time series available (2010-present). The comparison against both parent hypotheses (AMS-only and QHS-only) on the same out-of-sample period provides a clean value-add test. The 2x2 grid prediction (monotonic improvement as both components increase) is a strong falsification mechanism. However, Pre-Test 2 (analyst snippet detail) is an existential gate that must be resolved before full backtesting. |

**Key Risks:**
- Free analyst snippet quality: if <40% of snippets contain parseable causal claims >15 words, the pre-call component is unreliable and ACF degrades to QHS-only.
- Requires at least 5 analysts covering for meaningful diversity measurement, limiting universe to mid-to-large caps.

---

### RANK 6: A3-H3 — Management Credibility Trajectory (MCT)

**Verdict:** PROMOTE
**Agent:** Narrative Economist (Agent 3)
**Composite:** 6.75

**Mechanism (one sentence):** Tracking management's statement-to-actual accuracy (Revenue and GAAP EPS only) over 8+ quarters identifies credible managers whose guidance the market systematically underweights — the credibility of the source matters more than the guidance magnitude, and LLMs make this tracking possible at scale.

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 6 | Annualized long-only alpha of >5% over sector benchmark, concentrated in the first 3 months post-statement. The signal is long-biased (more positive than negative guidance from management), making the alpha primarily from avoiding low-credibility managers' guidance rather than capturing mispriced positive guidance. Respectable but not transformative. The edge is in the credibility filter's ability to improve the hit rate of guidance-following strategies. |
| Persistence | 8 | Implementation complexity (multi-stage extraction -> verification -> scoring pipeline across thousands of companies and millions of statement-to-actual pairs) creates a substantial moat. Even if the methodology is published, operationalizing it requires significant data engineering investment. The simplified scope (Revenue + GAAP EPS only) reduces the matching error rate from 20-40% to <10%, making the signal cleaner but also easier to replicate if the pipeline is ever commercialized. Decay horizon: 5+ years. |
| Robustness | 6 | The regime-change decay test (separate pre-shock and post-shock credibility scores when revenue changes >30% YoY) is a thoughtful addition that addresses the concern about credibility being regime-dependent. However, the multi-stage pipeline (extract -> structure -> verify -> score -> signal -> trade) has error propagation risk — a 15% extraction error compounded with 10% matching error could produce a credibility score noise floor that obscures the signal. The simplified metrics help but don't eliminate this concern. End-to-end pipeline testing on 20 companies before scaling is essential. |
| Novelty | 6 | This hypothesis directly extends well-established accounting research on management forecast credibility (Hutton & Stocken 2009; Rogers & Stocken 2005). The LLM's role is operationalizing something previously measurable only with coarse proxies (historical forecast error frequency) or tiny hand-collected samples. The contribution is making an established academic finding practically tradeable, not discovering a new phenomenon. Valuable, but more engineering than discovery. |
| Retail Feasibility | 7 | All data is free (transcripts, EDGAR filings, Yahoo Finance). The signal is long-biased, making it executable without shorting — a significant practical advantage. The 1-6 month holding period is manageable. However, the initial build cost is substantial: estimated 20-40 hours of pipeline development and $200-400 in initial LLM API costs for historical processing of 2010-present for the Russell 3000. This is feasible for a dedicated retail trader but represents a significant upfront investment. |
| Testability | 7 | Clean falsifiable prediction with monotonicity test across CS quintiles. The simplified metrics (Revenue + GAAP EPS) have the cleanest cross-document matching pathways. The walk-forward simulation (using only CS computed from prior statements verified as of each call date, no look-ahead) is the correct out-of-sample design. However, the statement-to-actual matching, even simplified, requires resolving different fiscal period definitions, segment restructurings, M&A, and accounting standard changes — the matching error rate must be measured before the credibility score is trusted. |

**Key Risks:**
- Error propagation in the multi-stage pipeline: extraction errors in stage 1 compound through verification and scoring.
- The signal is silent on new IPO management teams (no credibility history), limiting the tradeable universe.

---

### RANK 7 (tie): A5-H3 — App Store Review Functional Failure Language

**Verdict:** REVISE
**Agent:** Alternative Data Alchemist (Agent 5)
**Composite:** 6.15

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | Originally claimed 300bps excess negative return over 2 weeks as a leading signal. After reframing to "confirmation + classification edge," the edge is more modest: the signal confirms and classifies crises detected elsewhere, providing incremental precision rather than first-mover advantage. The edge per event is reduced but the hit rate should improve due to the persistence and cross-platform confirmation filters. |
| Persistence | 7 | Complex multi-platform, multi-classification pipeline (Apple App Store + Google Play + Trustpilot, with per-app FFR baselines and cross-platform confirmation) creates a meaningful moat. The universe is naturally limited (80-150 consumer-tech companies with material app presence), deterring institutional capital allocation. Decay horizon: 5+ years. |
| Robustness | 5 | Pre-Test 4 (leading-vs-lagging timestamps) is likely to show the app store signal is a fast-follower, not a leader. The reframed value proposition (confirmation + classification + persistence measurement) is more defensible but acknowledges a reduced role. The crisis persistence filter (2+ consecutive days above threshold) and cross-platform confirmation filter add robustness by eliminating transient issues and platform-specific noise. |
| Novelty | 8 | The core insight — that functional-failure reviews ("the app deleted my data") predict churn and revenue loss differently from preference complaints ("I hate the new design") — is genuinely sharp. No existing sentiment analysis tool or quant factor makes this distinction. The crisis-type taxonomy (BILLING_ERROR, DATA_LOSS, SECURITY_BREACH, CRASH_BUG, etc.) with different financial implications is an original contribution to consumer-tech equity analysis. |
| Retail Feasibility | 7 | Data collection is straightforward (RSS feeds for Apple App Store, google-play-scraper for Google Play, free Trustpilot pages). Daily collection of 200-5,000 reviews across 80-150 companies is feasible. LLM classification costs $50-150/month. 1-4 week holding period is manageable. The main friction is that the universe is small and short-side execution via put options on volatile consumer-tech names carries elevated premiums. |
| Testability | 6 | Backtesting historical app store review data is the bottleneck. Academic datasets and Kaggle have partial coverage but may not cover all target companies or have consistent historical depth. Pre-Test 4 (10-20 historical crises with four timestamps) must be completed before full backtesting. The reframed falsifiable prediction (social media + app store confirmation vs. social media alone) is testable but requires both data sources with aligned timestamps. |

**Key Risks:**
- Pre-Test 4 is likely to show the signal is a fast-follower, not a leader — requiring full reframing of the value proposition.
- Historical app store review data for backtesting is not perfectly archival, limiting backtest depth.

**Changes Required Before PROMOTE:**
1. Reframe the value proposition from "leading edge" to "confirmation + classification edge"
2. Adjust the falsifiable prediction to measure incremental value of app store confirmation over social media sentiment alone
3. Accept the MARGINAL PASS scenario for Pre-Test 4 (T_review lags by 6-24 hours is acceptable in reframed role)

---

### RANK 8 (tie): CTDS — CDS-Transcript Divergence Signal

**Verdict:** REVISE
**Agents:** Cross-Asset Synthesizer (Agent 4) + Earnings Whisperer (Agent 1) + Filing Archaeologist (Agent 2)
**Composite:** 6.15

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 7 | Predicted 500bps excess negative return over 3 months for DIVERGENCE-CONFIRMED stocks, with the effect concentrated in the first 6 weeks. The monotonic relationship across signal tiers (DIVERGENCE-CONFIRMED worst, DIVERGENCE-WEAK intermediate, DIVERGENCE-UNCERTAIN closest to zero) is a strong prediction. The dose-response relationship between CDS widening magnitude and equity underperformance is a clean causal test. However, only 20-30 DIVERGENCE-CONFIRMED signals per year limits absolute return potential. |
| Persistence | 8 | This is a cross-domain orphan: CDS traders do not systematically read earnings call transcripts for linguistic markers, and equity analysts do not systematically monitor CDS spreads. The signal requires three-domain integration (credit monitoring + linguistic baseline modeling + filing-based verification) that no single research department possesses. The specific insight — that the STRONGEST signal is CDS widening WITHOUT linguistic adaptation — is counterintuitive and unlikely to be discovered independently. Decay horizon: 5+ years. |
| Robustness | 3 | The CDS data accessibility problem is severe. Individual-name CDS requires paid subscriptions (Markit, ICE, Bloomberg). The FINRA TRACE corporate bond yield spread proxy introduces basis risk (bond-CDS basis can be volatile during credit stress, precisely when the signal would fire). The universe is limited to ~400-500 companies with liquid CDS, and after filtering for sufficient transcript history and filing coverage, the tradeable universe may be only 200-300 names. The signal fires episodically (30-50 widening events/year), and not all of these will be DIVERGENCE-CONFIRMED. |
| Novelty | 10 | The most genuinely novel hypothesis in the entire set. It could ONLY emerge from the intersection of three agents' domains: credit market monitoring (Agent 4) + linguistic normality detection (Agent 1) + filing-based credit verification (Agent 2). The specific insight — that the ABSENCE of linguistic distress combined WITH CDS widening is the strongest signal, because it means management is in denial and the narrative has not yet adapted — is something no single agent would have conceived. Agent 1 is trained to DETECT linguistic distress, not to note its absence. Agent 4 is trained to FOLLOW credit signals, not to condition them on narrative adaptation. |
| Retail Feasibility | 2 | This is the critical failure point. Individual-name CDS data is NOT retail-accessible for free. Markit, ICE, and Bloomberg all require paid subscriptions. The FINRA TRACE bond spread proxy is a partial workaround but introduces basis risk. Even with a data source, the universe is limited to 200-300 tradeable names. For live retail trading, the CDS data pathway does not currently exist at acceptable cost. This hypothesis may be strongest as an academic investigation rather than a retail trading strategy. |
| Testability | 5 | Backtesting with academic CDS data (e.g., WRDS Markit CDS) is feasible and would produce valid results. The falsifiable predictions are specific and well-structured (monotonicity, dose-response, placebo tests). However, the live trading data pathway is blocked — the hypothesis can be validated but not executed by a retail trader. The 50bps CDS widening threshold should be empirically calibrated rather than set a priori. The expected 15-25 DIVERGENCE-CONFIRMED signals per year is an upper bound; the actual may be lower. |

**Key Risks:**
- CDS data paywall is the binding constraint — without a viable retail data pathway, the hypothesis is academically interesting but practically dead for this project.
- FINRA TRACE bond spread proxy introduces bond-CDS basis risk that is most volatile during credit stress (exactly when the signal would fire).

**Changes Required Before PROMOTE:**
1. Specify exact CDS data source for both backtesting AND live trading — if no retail-viable pathway exists, KILL for retail (retain as academic investigation)
2. Calibrate the 50bps CDS widening threshold empirically from the training period distribution
3. Acknowledge the limited universe honestly — expected 15-25 DIVERGENCE-CONFIRMED signals per year is the tradeable ceiling

---

### RANK 9: A1-H2 — Scripted-Answer Echo Detection

**Verdict:** REVISE
**Agent:** Earnings Whisperer (Agent 1)
**Composite:** 5.80

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | Revised from 2.0x to 1.5x lift in negative-surprise probability, conditional on bottom 2/3 baseline-SQ executives. Translates to approximately 300bps of avoidable negative drift per flagged position. The conditional prediction narrows the tradeable universe to naturally conversational executives who suddenly become formal — reducing signal frequency but increasing precision. |
| Persistence | 7 | Requires processing both lengthy SEC filings (10-K/10-Q building a filing corpus) and transcripts simultaneously, plus a cross-company conversational baseline. The per-executive SQ baseline (analogous to H1) adds a barrier to replication. Shared 10-K ingestion infrastructure with Agent 2 reduces marginal cost. Decay horizon: 3-5 years. |
| Robustness | 4 | The fundamental causal ambiguity persists despite the per-executive baseline. A management team that is well-prepared because they have GOOD news (a transformative acquisition, a guidance raise) will produce high SQ relative to baseline — the per-executive baseline cannot distinguish "preparing for good news" from "preparing to conceal bad news." The post-call validation cross-check (only treat high SQ as bearish when the post-call surprise is negative) is still needed. |
| Novelty | 6 | The Scripting Quotient (filing similarity / conversational similarity) is an original metric, and the cross-corpus comparison (filing corpus vs. conversational baseline) is a creative use of embeddings. But the core idea — comparing Q&A language to formal document language — is a logical extension of existing text analysis methods. Moderately novel measurement, not a new concept. |
| Retail Feasibility | 7 | All data is free. The corrected cost estimate for filing corpus embedding is $20-80/quarter (not $200-500 as originally feared by the Skeptic). Shared 10-K ingestion infrastructure with Agent 2 reduces the marginal cost further. 1-4 week holding period is manageable. The short bias creates the same retail friction as H1 but inverse ETFs/puts are available workarounds. |
| Testability | 6 | The conditional prediction (signal only works for low-baseline-SQ executives) makes testing more complex — the sample must be split by baseline-SQ tercile, and statistical power in each tercile is lower. The conversational baseline corpus construction needs rigorous specification to avoid contamination. The conversation baseline should be drawn from Q&A responses verified as unscripted, which is a non-trivial data curation task. |

**Key Risks:**
- Causal ambiguity: high SQ can mean "hiding bad news" or "well-prepared for good news" — the per-executive baseline doesn't distinguish these.
- The conversational baseline corpus may be contaminated with scripted Q&A, degrading the SQ metric.

**Changes Required Before PROMOTE:**
1. Add a post-call validation cross-check: only treat high SQ as bearish when the post-call earnings surprise is negative
2. Narrow the falsifiable prediction for the conditional subset (bottom 2/3 baseline-SQ executives)
3. Specify the conversational baseline corpus construction more rigorously — verify unscripted Q&A sources

---

### RANK 10: A3-H1 — Q&A Coherence Decay (QACD)

**Verdict:** REVISE
**Agent:** Narrative Economist (Agent 3)
**Composite:** 5.45

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | Annualized long-short alpha >4% post-cost, with the short leg generating -3% abnormal return over the 60-100 day holding period. The within-call decay trajectory is a novel measurement, but the effect size is modest relative to the holding period length. The edge is concentrated in stocks where the narrative was particularly brittle, which may be a minority of calls. |
| Persistence | 5 | The methodology — embedding, cosine similarity, OLS slope fitting — is computationally intensive but straightforward to replicate once published. The holding period (1-6 months) sits in a horizon gap, but a published validation would attract quant fund attention within 1-2 years. Decay horizon: 3-5 years. |
| Robustness | 5 | Response-length control (log word count as covariate) and same-topic decay score (isolating semantic divergence from topic drift) address the two main confounds. However, the same-topic decay score may be computed from very few Q&A responses — if only 2-3 responses share a topic with prepared remarks, the slope is extremely noisy. A minimum-sample threshold (>=3 same-topic responses) is needed, and the percentage of calls meeting this threshold is unknown. The 2x2 matrix with A1-H2 (SQ x QACD) is a promising synergy but the interaction test has not been pre-registered. |
| Novelty | 7 | The within-call trajectory measurement — fitting a slope to the similarity decay over sequential Q&A responses — is genuinely novel. Most text-based approaches extract a single summary statistic (sentiment, readability); measuring the TEMPORAL DYNAMICS within a single earnings call is a fresh approach to narrative analysis. The same-topic decay score specifically isolates semantic divergence from topic drift, which is a careful methodological innovation. |
| Retail Feasibility | 6 | Data is free (transcripts, Yahoo Finance estimates). Processing is straightforward: embed, compute cosine similarity, fit OLS. LLM API costs are modest. The 1-6 month holding period is manageable. However, the signal is short-biased, and maintaining short positions (or rolling put options) for 1-6 months is expensive and psychologically demanding for a retail trader. |
| Testability | 6 | The controlled regression (similarity_i = alpha + beta_1 * i + beta_2 * log(word_count_i)) is well-specified. But the signal needs a quantitative decay threshold (e.g., beta_1 <= -0.03 for a short signal) calibrated on the training period. The same-topic decay score requires a minimum-sample threshold that may reduce the tradeable universe. The 2x2 interaction test with SQ needs pre-registration. |

**Key Risks:**
- Same-topic decay score may apply to too few calls (if <50% of calls have >=3 same-topic Q&A responses, the signal is too sparse).
- The signal is short-biased with a 1-6 month holding period — retail execution friction is significant.

**Changes Required Before PROMOTE:**
1. Add minimum-sample threshold for same-topic decay score (>=3 responses), and measure coverage
2. Specify a quantitative decay threshold for signal firing, calibrated on training data
3. Pre-register the 2x2 interaction test with A1-H2 (SQ x QACD)

---

### RANK 11: A2-H1 — Risk Factor Clean vs. Dirty Removal Drift

**Verdict:** REVISE
**Agent:** Filing Archaeologist (Agent 2)
**Composite:** 5.15

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 4 | Revised annualized alpha of 3-4% for the full universe, >6% for the low-analyst-coverage subset. The post-filing drift is concentrated in stocks where 8-K monitoring is least systematic — but this is also the segment with the highest transaction costs and lowest liquidity. The edge, while statistically significant in the conditional subset, is economically modest after costs. |
| Persistence | 6 | The two-stage mechanism (8-K partially priced -> 10-K triggers incremental discovery) is complex enough to deter simple replication. The multi-document reasoning step (cross-referencing Item 1A vs. Legal Proceedings vs. MD&A vs. 8-Ks) provides a moat. However, quant funds already scrape EDGAR for textual changes, and the clean/dirty distinction, while clever, is a classification task that can be replicated. Decay horizon: 3-5 years. |
| Robustness | 3 | The temporal confounding problem is the core challenge and has not been fully resolved. The hypothesis now predicts that post-filing drift is concentrated in low-coverage stocks — but this could equally be explained by slow 8-K information diffusion (which happens to coincide with the 10-K filing date) rather than the 10-K filing TRIGGERING discovery. The filing-date discontinuity test (is there a volume and CAR "step down" ON the filing date?) is required to distinguish these mechanisms but has not been specified. |
| Novelty | 7 | The clean/dirty distinction for risk factor removals is clever and genuinely under-exploited. The specific operationalization — cross-referencing the removed risk factor against Legal Proceedings, MD&A, and contemporaneous 8-Ks to classify the removal type — requires multi-hop reasoning that is a genuine LLM advantage. The academic literature on risk factor disclosures focuses on counts and topic models, not cross-document resolution classification. |
| Retail Feasibility | 6 | All data is free (SEC EDGAR). The processing pipeline requires downloading and parsing 3-5 GB of raw filing text per quarter for the Russell 3000 — feasible on a consumer-grade computer with an overnight batch process. However, LLM API costs for multi-document reasoning on 3,000+ companies would be $300-600/quarter, at the upper end of retail budget. The 1-4 week holding period is manageable. |
| Testability | 6 | The temporal decomposition test (pre-filing CAR vs. post-filing CAR) is well-specified and should be the first empirical check. The additional filing-date discontinuity test is needed but adds complexity. The conditional prediction by analyst coverage reduces sample size in the most favorable subset. The <5 analysts threshold for the strong-signal subset is specific and falsifiable. |

**Key Risks:**
- The filing-date discontinuity test must show the 10-K TRIGGERS price discovery, not just COINCIDES with ongoing drift.
- If pre-filing CAR accounts for >80% of total adverse return even in the low-coverage subset, the hypothesis is falsified.

**Changes Required Before PROMOTE:**
1. Add a filing-date discontinuity test: measure CAR and volume jump ON the 10-K filing date
2. Specify analyst coverage threshold concretely: "<5 analysts" for the strong-signal subset
3. Tighten the falsification condition: if pre-filing CAR >80% of total in the <5-analyst subset, hypothesis is dead

---

### RANK 12: A6-H2 — Pre-Earnings Abnormal Short Flow

**Verdict:** REVISE
**Agent:** Microstructure Mechanic (Agent 6)
**Composite:** 4.70

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | Mean 5-day excess return >2% for squeeze setups meeting all criteria. After capacity constraints (3% of ADV for position sizing), the per-trade return falls to >0.5%. The strategy has high gross returns that are significantly compressed by capacity constraints — the edge exists but doesn't scale. |
| Persistence | 5 | The mechanism (trapped shorts forced to cover) is a real market phenomenon. Short squeezes happen regularly, and the combination of pre-earnings positioning + post-earnings catalyst resolution is a sensible hunting ground. However, if the signal works consistently, short sellers would adapt by covering earlier, eroding the pre-earnings short volume spike. Decay horizon: 2-4 years. |
| Robustness | 3 | FINRA short volume data quality is the fundamental limitation. Daily short sale volume includes substantial market-maker shorting for liquidity provision, which is NOT directional. On high-volume earnings weeks, market-maker short volume mechanically increases. The volume-normalization refinement (SV% / volume ratio) helps but cannot fully disentangle market-maker from directional shorting — the proportion between them is unknown and varies across stocks and time. The signal is testing a NOISY PROXY for directional shorting, not actual directional shorting. |
| Novelty | 5 | The quant-only baseline ("buy heavily shorted stocks that beat earnings") is a known strategy. The LLM transcript classification (SQUEEZE_SETUP vs. SHORTS_CONFIRMED vs. NO_EDGE) is the novel contribution. The hypothesis stands or falls on whether the LLM classification adds incremental value beyond the quant baseline — and this has not yet been tested. |
| Retail Feasibility | 5 | FINRA short volume data is free but delayed. Securities lending data is partially free (iborrowdesk.com) but may not cover all names or update with sufficient frequency. Transcripts are free. However, after-hours gap risk is significant: by the time the transcript is published, the stock may have already moved. Entry at close on transcript publication day partially mitigates this but doesn't eliminate it. |
| Testability | 5 | The tiered testing approach (quant-only baseline first, then LLM-enhanced) is methodologically correct. The key test — does the LLM classification improve hit rate beyond the quant baseline? — is well-specified. However, the FINRA data noise sets a ceiling on signal detectability: even a genuine effect may be too attenuated by the noisy proxy to reach statistical significance. |

**Key Risks:**
- FINRA short volume data is a noisy proxy for directional shorting — the noise may obscure a genuine signal.
- The quant-only baseline may show zero or negative excess returns, making the LLM component moot.

**Changes Required Before PROMOTE:**
1. Run quant-only baseline test first — KILL if excess returns <0.5% over 5 days
2. If baseline works, test LLM increment — requires at least 10-percentage-point hit rate improvement
3. Acknowledge the FINRA data limitation honestly in effect size estimates

---

### RANK 13: A5-H2 — Job Posting Semantic Pivot (SPI)

**Verdict:** REVISE
**Agent:** Alternative Data Alchemist (Agent 5)
**Composite:** 4.55

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 5 | 300bps excess return over a 3-month holding period with 1.5-1.7x lift in positive revenue surprise rates. The edge is moderate and spread over a long holding period. The mechanism (companies hire for what they intend to do, and the STRATEGIC DIRECTION of hiring reveals strategy before financials) is economically sound. |
| Persistence | 4 | Alternative data vendors (Revelio Labs, LinkUp, Thinknum) would add semantic classification to their existing job posting count products within 12-24 months of a published validation. The initial moat from the data collection barrier (scraping hundreds of career pages) erodes quickly once commercial vendors incorporate the signal. Decay horizon: 2-4 years. |
| Robustness | 4 | Three compounding noise sources: (a) evergreen postings that stay up continuously regardless of hiring need, (b) HR boilerplate that obscures strategic intent, and (c) the intent-vs-outcome gap (companies hire for expansion but projects get cancelled). The evergreen detection filter (>90% text similarity + >90 days active) and boilerplate stripping help but don't fully resolve these issues. The 50-company curated universe for initial validation is smart but limits generalizability. |
| Novelty | 8 | This is one of the most original ideas in the set. The distinction between expansion hiring ("launch," "greenfield," "0-to-1") and optimization hiring ("streamline," "automate," "consolidate") is economically meaningful, and no existing commercial dataset classifies job postings by strategic intent. The SPI metric is a genuinely new measurement. Unlike many other hypotheses that operationalize known academic findings, this proposes a new data-to-signal pathway. |
| Retail Feasibility | 3 | Data collection is the elephant in the room. Scraping 200-500 company career pages daily, plus LinkedIn/Indeed/Glassdoor, while staying within rate limits and handling JavaScript-rendered pages, is a significant ongoing engineering commitment. Many career pages use anti-bot measures. The maintenance burden for a retail trader is high. Historical backtesting via Wayback Machine has severe coverage bias (large companies archived, small companies not). |
| Testability | 4 | Backtesting is severely constrained by data availability. Internet Archive Wayback Machine coverage is sparse and biased — large, well-known companies have good coverage; small/mid-caps have spotty coverage. The companies with the best archival coverage are also the ones that survived and grew, creating survivorship bias. The 50-company curated universe is a reasonable starting point but if SPI fails there, the hypothesis is killed for the broader universe. Live-forward testing may be more practical than historical backtesting. |

**Key Risks:**
- The data collection burden for live trading is substantial — scraping career pages is an ongoing engineering task, not a one-time pipeline.
- If the 50-company curated universe validation fails, the hypothesis has no path forward.

**Changes Required Before PROMOTE:**
1. Conduct 50-company validation FIRST — KILL if IC < 0.03 for revenue surprise prediction
2. Demonstrate that SPI predicts revenue surprises BEFORE analysts revise estimates (if <30% lead, the signal is lagging)
3. Specify minimum posting count per product area (>5 NEW postings per quarter)

---

### RANK 14: A7-H3 — Retail Options Flow Exhaustion

**Verdict:** REVISE
**Agent:** Behavioral Contrarian (Agent 7)
**Composite:** 4.45

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 4 | Predicted 2% reversal in stock price over 5 days, with options returning 3x premium paid. The edge is asymmetric (winners > losers) but the win rate with T+1 entry is likely lower than the original claim — probably 52-55% rather than 55%+. After options spread costs, the net edge is thin and sensitive to win rate. |
| Persistence | 4 | Retail options flow is widely followed — Barchart, Unusual Whales, FlowAlgo, and CheddarFlow all have large user bases. The narrative context filter (FOMO vs. catalyst) is the novel contribution, but if it works consistently, it would be incorporated into these existing products quickly. Decay horizon: 2-4 years. |
| Robustness | 4 | Three fragility points: (a) T+1 entry must be validated first — if reversals are intraday, the signal is dead, (b) institutional flow masquerading as retail (algorithms splitting large orders into small lots) contaminates the retail identification with uninformed "fade" signals, and (c) the FOMO-vs-Catalyst boundary is inherently blurry despite the hard 8-K rule. The refined retail identification (consistent small-lot + NBBO + single-exchange) helps but doesn't eliminate the contamination problem. |
| Novelty | 6 | The three-stage sequential filter (quant extreme + narrative context + execution) is well-designed. The narrative context filter — distinguishing between "flow arriving because of genuine catalyst" (do NOT fade) and "flow arriving because the stock is up and Reddit loves it" (FADE) — is a genuine insight. But fading retail options flow is a well-known strategy; the narrative filter is an improvement, not a discovery. |
| Retail Feasibility | 5 | Data is free/freemium but delayed (15-20 minutes for CBOE, potentially end-of-day for Barchart free tier). The signal has been revised to T+1-only entry, which is the correct adjustment but may reveal no predictive power. Options execution on extreme retail interest names carries elevated implied volatility premiums — the names you want to fade are precisely the names where options are most expensive. |
| Testability | 5 | The T+1 viability test (day-T flow predicts T+1 to T+6 reversal) is clean and dispositive. The LLM filter value-add test (Stage 1 alone vs. Stage 1+2) is well-structured. However, the retail identification false-positive rate must be estimated — if >30% of "retail-identified" flow occurs on 8-K filing days (which should be CATALYST and excluded), the identification is unreliable. Additionally, small-lot classification from low-volume option names is statistically unreliable. |

**Key Risks:**
- T+1 entry may show zero predictive power — if reversals happen intraday, the signal is not actionable for retail.
- The narrative filter may not add incremental value beyond the simple quantitative screen.

**Changes Required Before PROMOTE:**
1. Resolve T+1 viability — KILL if hit rate <=50%
2. Test narrative filter increment — requires at least 5-percentage-point hit rate improvement
3. Add minimum options volume filter (>1,000 contracts on signal day)
4. Acknowledge retail identification false-positive rate with specific estimate

---

### RANK 15: A4-H1 — Supply Chain Shock Transmission via 10-K

**Verdict:** REVISE
**Agent:** Cross-Asset Synthesizer (Agent 4)
**Composite:** 3.70

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 3 | Original -80bps excess return over 5 days. After accounting for Cohen-Frazzini decay and the likelihood that name-resolution covers primarily known relationships, the incremental LLM alpha is likely -20 to -40bps in mid/small-cap. After transaction costs for illiquid small-cap supplier names (50-100bps bid-ask spreads), the net edge may be near zero. |
| Persistence | 3 | Cohen & Frazzini (2008) is 18 years old. Institutional supply-chain databases (Bloomberg SPLC, FactSet Supply Chain) have expanded substantially. The C-F decay baseline must be established first, and the replication is likely to show the effect has substantially decayed — from the original ~150bps/month to near zero in large caps and perhaps -30bps in small caps. The LLM's incremental contribution depends on the residual C-F effect being nonzero. |
| Robustness | 3 | Multiple pre-test gates, each of which is likely to constrain the hypothesis: (a) name-to-ticker resolution likely <70%, creating systematic coverage gaps biased against the most interesting (private company customer) relationships, (b) C-F replication likely shows substantial decay, and (c) the liquidity filter (spread <30bps, ADV >$5M) eliminates many of the mid/small-cap names where the signal is supposed to be strongest. |
| Novelty | 5 | The LLM extraction from 10-K footnotes for customer/supplier relationships is a genuine improvement over standardized segment data. But the underlying mechanism — customer-supplier return predictability — is one of the most famous anomalies in empirical finance. The LLM contribution is incremental (finding additional relationships in footnotes), not foundational (discovering the phenomenon). |
| Retail Feasibility | 5 | All data is free (SEC EDGAR, Yahoo Finance). Dependency graph construction is quarterly batch processing. The 1-5 day holding period is manageable. However, short-selling mid/small-cap supplier names — the names where the signal is strongest — faces wide bid-ask spreads, potential borrow unavailability, and illiquidity. The 20-30bps round-trip cost estimate is optimistic for small-cap names. |
| Testability | 5 | Three sequential gates must be resolved before full backtesting: (a) Pre-Test 5 (name resolution rate), (b) C-F decay baseline replication, (c) comparison of LLM-only vs. overlapping relationships. Each gate has the potential to kill the hypothesis. Even if all gates pass, the incremental LLM alpha may be below transaction costs (<20bps) — statistically significant but economically irrelevant. |

**Key Risks:**
- Pre-Test 5 (name resolution) is likely below 70% — unresolved relationships skew toward private company customers, exactly the most alpha-generating relationships.
- The C-F replication is likely to show the effect has substantially decayed.
- Even if "real," the incremental LLM alpha may be below transaction costs.

**Changes Required Before PROMOTE:**
1. Resolve Pre-Test 5 first — KILL if resolution rate <60%
2. Establish C-F baseline on 2020-2024 — the LLM must provide incremental alpha on top
3. Specify expected incremental alpha quantitatively — if <20bps, the hypothesis is uneconomical

---

### RANK 16: A4-H3-Revised — Post-FOMC Factor Regime Classification

**Verdict:** REVISE
**Agent:** Cross-Asset Synthesizer (Agent 4)
**Composite:** 3.50

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Edge Magnitude | 3 | Predicted 100bps annualized outperformance over static 60/40 portfolio through quarterly factor tilts. With only 8 rebalances per year, the edge per rebalance is approximately 12.5bps. The effect is small and spread over long holding periods — even if real, the absolute return contribution is modest relative to the noise of factor returns. |
| Persistence | 2 | FOMC statements are the most parsed documents in global finance. Every fixed-income desk, macro hedge fund, and central bank watcher reads them with extreme care. Algorithmic trading systems parse the rate decision in milliseconds. The idea that an LLM's concern classification provides an edge that professional Fed watchers and systematic macro strategies miss is a very high bar. If the edge exists, it is likely already incorporated into factor timing models. |
| Robustness | 3 | The hypothesis must first demonstrate that the LLM concern classification is NOT just a hawkish/dovish proxy. If regressing the LLM classification on Fed Funds futures changes, 2-year yield changes, and breakeven inflation rates yields R-squared >0.70, the LLM adds no information beyond what rates markets already price. The critical independent-variation test (R-squared <0.50 required) is a high bar that the LLM may not clear. |
| Novelty | 4 | Factor timing based on Fed policy is one of the most studied topics in macro investing. The LLM concern classification is a different measurement tool, but the application (tilt factor exposures based on Fed stance) is standard. Slightly novel measurement applied to a well-studied problem. |
| Retail Feasibility | 8 | The most feasible hypothesis for retail execution. Data is completely free (Fed website, Yahoo Finance). Only 8 rebalance events per year, requiring minimal time commitment. Factor ETFs (IWD/IWF for Value/Growth, XLY/XLP for Cyclical/Defensive) are highly liquid with tight spreads. No short-selling required for factor tilts. A retail trader would spend about 2-3 hours per FOMC meeting (8 times/year) on this strategy. |
| Testability | 4 | 60 quarterly observations (2011-2025) is small but manageable for factor timing tests. A Bayesian approach with an informed prior centered at zero predictive power is appropriate. The pre-registered factor timing test (freeze LLM prompts on 2011-2018, test on 2019-2025) is well-designed. However, with only ~28 observations in the test set, statistical power is limited and the posterior distribution of the IC will be wide. |

**Key Risks:**
- The LLM concern classification may be indistinguishable from a simple hawkish/dovish proxy — in which case it adds no value.
- Even with the revised scope (60 quarters instead of 40-60 events), statistical power is limited.

**Changes Required Before PROMOTE:**
1. Demonstrate LLM classification is NOT just a hawkish/dovish proxy (R-squared <0.50 with market rates)
2. Pre-register the factor timing test with exact ETFs and evaluation metric
3. Acknowledge sample size limitation honestly and use Bayesian estimation

---

## 4. TOP 5 DEEP-DIVE: COMPREHENSIVE ANALYSIS

### 4.1 Rank 1: A5-H1 — FDA Briefing Document Asymmetric Skepticism (8.30)

**Why it ranks first:** This hypothesis achieves the highest composite score because it excels across ALL dimensions simultaneously — something no other hypothesis achieves. It has the highest Edge Magnitude (8), shares the highest Persistence (9), has the highest Robustness (8), near-highest Novelty (8), solid Feasibility (7), and the highest Testability (9). No other hypothesis scores above 7 on more than four dimensions; A5-H1 scores 7+ on all six.

**The mechanism in detail:** FDA staff reviewers write advisory committee briefing documents ahead of PDUFA dates. These reviewers are career regulators who cannot explicitly say "this drug should not be approved" without prejudicing the advisory committee process. Instead, they encode their skepticism through asymmetric language: hedging benefit claims with conditional constructions ("may provide benefit," "could be considered," "some evidence suggests") while stating safety concerns in definitive, unhedged language ("was associated with," "resulted in," "occurred in X% of patients"). The Benefit-Risk Linguistic Asymmetry Score (BRLAS) operationalizes this as: BRLAS = (Hedging_benefit - Hedging_risk) + (Certainty_risk - Certainty_benefit) + 0.5 * (Readability_benefit - Readability_risk). A positive BRLAS means the reviewer hedges benefits more than risks and is more certain about risks than benefits — the skeptical pattern.

**Why it is structurally durable:**
- FDA documents are 50-200 pages of dense medical, statistical, and regulatory prose. Processing them requires domain knowledge (understanding clinical trial endpoints, adverse event reporting, statistical analysis plans) that creates a natural barrier to entry.
- Per-reviewer normalization (tracking individual reviewer BRLAS baselines across multiple drug reviews, where reviewer names are available on ~60-70% of documents) controls for the "institutional writing conventions" confound — the concern that FDA reviewers write cautiously about benefits as a matter of style guide, not drug-specific skepticism.
- The universe is naturally limited (150-200 PDUFA drugs per year), making it too small for institutional capital allocation — this is a feature for retail durability, not a bug.
- The data is fully archival (every historical FDA briefing document back to at least 2017 is on fda.gov), making backtesting straightforward and comprehensive.

**Why it is retail-feasible:** All data is free and archival. Briefing documents are published on a deterministic schedule (2 business days before advisory committee meetings). The 1-5 day holding period is ideal for retail execution — enter on briefing document publication, exit on FDA decision announcement. Put options provide defined-risk short exposure on binary biotech events. The LLM pipeline can process documents as they are released. The main barrier is domain knowledge: understanding FDA document structure, drug review processes, and interpreting BRLAS scores in context requires familiarity with regulatory medicine. However, the LLM handles the heavy linguistic lifting, so the trader only needs to understand the output, not the medical content.

**Most important empirical test:** Whether BRLAS provides incremental predictive power beyond what option prices already reflect. Pre-PDUFA biotech implied volatility is 150-300% — the options market already prices a probability distribution over FDA outcomes. If BRLAS merely confirms what options prices already reflect, the edge is zero. The hypothesis requires that BRLAS-flagged drugs have a higher actual CRL rate than what option-implied probabilities suggest.

**If this hypothesis fails, it likely fails because:** (1) option markets are efficient and already price the linguistic signals that BRLAS measures, (2) reviewer heterogeneity within divisions is too high for per-reviewer normalization to work (insufficient reviewer-specific history), or (3) FDA document format changes over time invalidate the linguistic baselines computed on historical documents.

---

### 4.2 Rank 2: A2-H2 — CAM Expansion Velocity as Distress Precursor (7.40)

**Why it ranks second:** This hypothesis achieves the highest scores on Persistence (9), Novelty (9), and Retail Feasibility (9). It is held back by moderate Edge Magnitude (5) — the structural lag between auditor identification and public disclosure means some deterioration is already priced. But the combination of a genuinely novel measurement, a regulatory mandate that ensures data consistency, and extremely low retail costs makes it the most well-rounded hypothesis after A5-H1.

**The mechanism in detail:** Critical Audit Matters (CAMs), required in auditor reports since 2019 under PCAOB AS 3101, are the issues that the external auditor identified as involving especially challenging, subjective, or complex judgment. When an auditor adds a NEW CAM in a topic cluster not previously associated with that company, it signals that the auditor has identified a deteriorating area of the business. The LLM's contribution is: (a) extracting CAM paragraphs with high precision despite formatting variability across audit firms (Deloitte, PwC, EY, KPMG each format their reports differently), (b) embedding CAM paragraphs and clustering them into a market-wide taxonomy of CAM topics, and (c) detecting when a company's CAM set expands into a new cluster — a cross-sectional anomaly detection that no existing system performs.

**Why it excels on Novelty:** CAM reporting is new (mandatory since 2019-2020). The academic literature is thin and focused on audit fees and auditor liability — not stock returns. No commercial data product (Bloomberg, FactSet, Compustat) systematically parses CAMs. The market views the auditor's report as a binary pass/fail signal (unqualified vs. going concern). Treating it as a continuous, multi-dimensional signal source — measuring the VELOCITY and DIRECTION of auditor concern expansion — is a genuinely new approach to using audit data in equity analysis.

**Why it is the most feasible hypothesis for retail:** All data is free (SEC EDGAR). Processing is quarterly batch, not daily. LLM costs are $30-90/quarter — the lowest of any hypothesis. The 1-6 month holding period requires patience but minimal trading activity. No short-selling is required. A retail trader could implement this by running the CAM extraction pipeline once per quarter (after 10-K filing season), reviewing the flagged names, and adjusting their portfolio — approximately 4-6 hours of work per quarter.

**The critical empirical test: the auditor-timeliness test.** Does CAM expansion predict negative returns even when the most recent earnings release showed STABLE or GROWING revenue/earnings? If CAM expansion only "predicts" what is already visible in deteriorating reported financials, the CAM adds nothing beyond standard financial statement analysis. The hypothesis is validated ONLY if CAM expansion predicts negative returns in the stable-earnings subset — which would mean auditors are identifying LATENT problems not yet visible in reported numbers.

**If this hypothesis fails, it likely fails because:** (1) auditors identify problems too late — by the time the CAM is published in the 10-K (60-90 days after fiscal year-end), 1-2 quarterly earnings releases have already revealed the deterioration, or (2) CAM changes are too infrequent to construct diversified portfolios (most companies have stable CAM sets year-over-year).

---

### 4.3 Rank 3: A2-H3 — Departure Language Severity as Screening Tool (7.25)

**Why it ranks third:** This hypothesis achieves the highest Retail Feasibility score in the set (10) and shares the highest Persistence (9). It is held back by moderate Edge Magnitude (5) — as a screening tool, its value is in risk reduction, not alpha generation. But for a retail long-only portfolio, avoiding catastrophic single-stock blowups is among the highest-value activities.

**The mechanism in detail:** When a company files an 8-K Item 5.02 (Departure of Directors or Certain Officers), the market's reaction is primarily driven by WHO left (CEO, CFO, key executive). However, the SPECIFIC LANGUAGE used to describe the departure contains a rich gradient of severity: sudden departures ("effective immediately" vs. "effective in 90 days"), perfunctory vs. effusive farewells (fewer than 30 words vs. 80+ words citing specific accomplishments), and co-occurrence with investigation language. The LLM extracts these linguistic features and constructs a Departure Severity Score that concentrates 35% of all subsequent adverse events (restatements, material weaknesses, SEC investigations, -50%+ earnings crashes) in the top decile of the score — a 3.5x concentration of blowup risk.

**The rescoping lesson:** The original hypothesis proposed a directional short strategy. The Skeptic identified that an 80-90% false positive rate makes directional shorting uneconomical (death by negative carry). The agent rescoped to a negative screening tool: "avoid stocks in the top decile of Departure Severity Score." This transforms the economic proposition from "generate alpha from short positions" (unviable) to "reduce drawdowns and avoid blowups in a long portfolio" (viable and valuable). This rescoping pattern — recognizing that moderate-precision signals are better deployed as screens than as trades — is a key methodological lesson from Stage 1.

**Critical design choice:** The CEO/CFO departure features are DOWNWEIGHTED (because the market already efficiently processes these) and language features (thank-you length, suddenness, investigation co-occurrence) are UPWEIGHTED. This makes the signal orthogonal to the known "CEO departure = bad" effect — it must add value where the market is NOT already paying attention.

**If this hypothesis fails, it likely fails because:** (1) selection bias — companies in the most extreme distress (fraud, imminent bankruptcy) may not file clean 8-Ks at all, so the Departure Severity Score misses the true black swans, or (2) the 3.5x concentration claim does not hold when verified against a list of known historical blowups.

---

### 4.4 Rank 4: A1-H1 — The Pronoun Divergence Signal (7.10)

**Why it ranks fourth:** This hypothesis is tied with ACF at 7.10 but is ranked higher based on dimension-level tiebreaking (higher Testability and Persistence). It represents the most tightly grounded causal mechanism in the set — the application of established psycholinguistics research (Pennebaker, Larcker & Zakolyukina) to earnings call Q&A. It was the first TENTATIVE PASS from Round 2 and survived all rounds of adversarial review with meaningful but non-destructive revisions.

**The mechanism in detail:** During earnings calls, prepared remarks are scripted, lawyered, and polished. Q&A forces management to answer without a script. When executives possess undisclosed negative information, they unconsciously distance themselves from the bad news by shifting from first-person plural pronouns ("we decided to...") to depersonalized constructions ("the decision was made to..."). This psychological distancing, measured as the Pronoun Participation Ratio (PPR = count of "we" + "us" + "our" / count of all pronouns), drops below the executive's personal 10th percentile baseline. The mechanism was broadened from "concealment" to "uncertainty or concealment" during Round 3 — both are bearish, and the asymmetric prediction (pronoun drops predict negative returns; pronoun spikes do NOT predict positive returns) holds.

**Why the per-executive baseline is the critical innovation:** Without it, the signal would flag executives who naturally use fewer first-person pronouns (a personality trait, not a deception signal). With 8+ quarters of per-executive history, the signal identifies deviation from personal norms. This is the kind of measurement that only an LLM can perform at scale — a human analyst cannot track 4,000 earnings calls per quarter and compute per-executive, per-topic pronoun ratio distributions against historical baselines.

**The falsification mechanism is unusually strong:** If pronoun divergence predicts negative returns, it should be ASYMMETRIC — pronoun increases (above 90th percentile) should NOT predict positive returns, because psychological distancing is a unidirectional signal of distress, not enthusiasm. If both pronoun drops AND pronoun spikes predict returns in their respective directions, the signal is just a measure of executive emotional variability (which could be driven by many factors), not psychological distancing. The asymmetry test is a strong falsification mechanism.

**If this hypothesis fails, it likely fails because:** (1) transcript fidelity — even EDGAR-filed transcripts are sometimes cleaned/paraphrased in ways that alter pronoun ratios without the pre-filter catching it, or (2) the effect is concentrated in a small subset of executives/calls and is not economically meaningful in aggregate.

---

### 4.5 Rank 5: ACF — Analyst Consensus Fragility (7.10)

**Why it ranks fifth:** The merged ACF hypothesis is a genuine methodological achievement — it measures consensus fragility at two points in the earnings cycle using two different data sources, and the cross-stage theme matching (consistent vs. inconsistent) is a novel insight that neither parent hypothesis could produce. It is held back by its dependence on free analyst snippet quality and the requirement for at least 5 analysts covering.

**The merger value proposition:** Neither parent hypothesis alone could distinguish between "warranted consensus" (analysts independently arrive at the same conclusion because the company's situation genuinely warrants it) and "fragile consensus" (analysts are in an information cascade, repeating each other's theses). The merged ACF does this by requiring that consensus manifest at TWO points: pre-call (analyst reports cite the same reasons) AND during-call (analyst questions probe the same topics). Only when BOTH conditions are present, the themes match across stages, AND analysts don't revise estimates after the call (revealing they didn't believe their own thesis enough to act on it), is the consensus unambiguously fragile.

**Graceful degradation is a built-in strength:** If free analyst snippet quality is poor (Pre-Test 2 fails), the pre-call argument diversity measurement is unreliable. But the ACF framework degrades gracefully to the QHS-only version (during-call question homogeneity), which uses full transcripts and is unaffected by snippet quality. This is not a "single point of failure" design — it's a convergent measurement framework that survives partial data quality failure.

**The cross-stage theme matching is the LLM's unique contribution:** The LLM compares the dominant pre-call argument theme ("strong AI pipeline growth") to the dominant during-call question theme ("AI pipeline monetization timeline") and classifies them as CONSISTENT or INCONSISTENT. If the themes are INCONSISTENT — analysts were bullish about AI but asked about margin compression during the call — the consensus fragility signal is weaker because the groupthink is not coherent. This theme-matching step requires cross-referencing the outputs of two separate LLM analyses and performing a semantic comparison that only an integrated pipeline can do.

**If this hypothesis fails, it likely fails because:** (1) free analyst snippet quality is insufficient for meaningful argument diversity measurement, degrading ACF to QHS-only (which may or may not work independently), (2) the joint conditions are so restrictive that the signal fires too rarely to be economically meaningful, or (3) the post-call estimate revision filter eliminates most signals (analysts DO revise estimates after most calls, making fragile consensus rare).

---

## 5. KILLED HYPOTHESES APPENDIX: "WHAT-IF" SCORES

These six hypotheses were KILLED in Round 4. Each is scored below on a "what-if" basis: the score it WOULD have received if its fatal flaw were magically fixed, to inform future research direction.

### KILLED Ranking by What-If Score

| Rank | Hypothesis | Agent | Fatal Flaw | Edge | Persist | Robust | Novelty | Feasibility | Testability | **What-If Composite** |
|------|-----------|-------|------------|------|---------|--------|---------|-------------|-------------|----------------------|
| K1 | A1-H3: Hesitation-Cluster Anomaly | A1 | Transcripts strip involuntary hesitation markers; hedge cluster workaround measures a different construct | 6 | 8 | 5 | 9 | 5 | 4 | **6.25** |
| K2 | A7-H2: Analyst Initiation Clustering | A7 | Free-tier initiation summaries lack detail for bandwagon-vs-substantive classification | 4 | 6 | 5 | 7 | 5 | 5 | **5.20** |
| K3 | A6-H3: ETF Creation Flow | A6 | T+1/T+2 reporting lag means price impact has already occurred | 5 | 5 | 4 | 6 | 6 | 5 | **5.05** |
| K4 | A4-H3 (original): Post-FOMC Divergence Resolution | A4 | ~20-25 test-set events insufficient for statistical validation | 5 | 6 | 3 | 8 | 7 | 2 | **5.00** |
| K5 | A4-H2: Commodity Cost Transmission | A4 | Three compounding problems: sector beta + stale data + no delay | 5 | 3 | 4 | 6 | 6 | 6 | **4.70** |
| K6 | A6-H1: Dealer Gamma Imbalance | A6 | Structural asymmetry — can't front-run market makers with stale data | 4 | 2 | 3 | 5 | 3 | 5 | **3.50** |

### K1: A1-H3 — Hesitation-Cluster Anomaly (What-If: 6.25)

**Fatal flaw:** Free transcript sources systematically strip involuntary hesitation markers (filled pauses, false starts). The Round 3 workaround — weighting toward "hedge clusters" — changes what is being measured from involuntary cognitive struggle to deliberate caution, a different construct requiring different causal logic.

**What would need to change to rescue this hypothesis:** Verbatim transcripts with preserved fillers ("um," "uh") and false starts would need to become universally available for free. This requires either: (a) SEC rulemaking that mandates verbatim transcript filing (unlikely), (b) a free transcript provider that explicitly preserves filler words and disfluencies (none currently exist at scale), or (c) Whisper-based transcription becoming cheap enough for retail-scale processing (currently $2,000-5,000/quarter, needs to drop by 10-20x).

**What-If Analysis:** If verbatim transcripts were available, this hypothesis would score very well. The mechanism — cross-company hesitation clustering as a sector-level cognitive disruption signal — is genuinely novel (Novelty: 9). The signal would be highly persistent due to its cross-company, cross-sector complexity and infrequent firing (Persistence: 8). The edge magnitude (200bps sector underperformance) is meaningful for sector ETF trades (Edge: 6). However, signal sparsity (2-4 fires/year) limits testability (Testability: 4) and retail feasibility (Retail: 5 — the patience required is extreme). The macro confounding concern (FOMC/CPI/NFP events producing correlated hesitation) would persist even with verbatim transcripts (Robustness: 5).

**Research direction:** If verbatim transcripts become available, this hypothesis should be the FIRST resurrected from the KILLED pile. The underlying idea — measuring industry-level cognitive disruption from executive speech patterns — is too creative to abandon permanently. Monitor transcript provider fidelity standards and Whisper API pricing.

---

### K2: A7-H2 — Analyst Initiation Clustering (What-If: 5.20)

**Fatal flaw:** Free-tier initiation summaries (2-3 sentence snippets from MarketBeat, TipRanks) lack sufficient detail for the bandwagon-vs-substantive classification that gives the hypothesis its LLM-specific edge. Without reliable classification, the signal reduces to "fade clustered positive initiations" — a known momentum reversal effect, not a novel LLM edge.

**What would need to change:** Full analyst initiation reports would need to be available for free or at very low cost. This is unlikely — analyst reports are the core product that sell-side research departments sell. Alternatively, a free data source that provides detailed initiation summaries (200+ words with specific thesis elements) would need to exist. Current free sources (MarketBeat, TipRanks) provide only rating, price target, and one-sentence commentary.

**What-If Analysis:** With full reports, the bandwagon-vs-substantive classification becomes viable and the hypothesis improves substantially. The behavioral mechanism (initiation clustering as peak discovery, bandwagon language confirming no new information) is well-grounded (Novelty: 7). Persistence would be high due to the low frequency and difficulty of systematization (Persistence: 6). However, the base rate limitation (15-25 qualifying events/year) caps Edge Magnitude (4) and Retail Feasibility (5) even with perfect data. The sector-relative pair trade (short stock, long sector ETF) partially addresses the short-bias-in-bull-market concern (Robustness: 5).

**Research direction:** Explore whether academic data shares (e.g., WRDS I/B/E/S detail with analyst report text) could provide sufficient historical data for a validation study. If the bandwagon signal is validated in an academic context, it could justify a paid data subscription for live trading — but the economics would need to overcome the $10K+/year analyst report data cost.

---

### K3: A6-H3 — ETF Creation Flow (What-If: 5.05)

**Fatal flaw:** The T+1/T+2 reporting lag on ETF shares outstanding means the retail trader observes creation activity AFTER the authorized participant has already executed the basket purchase and the price impact has occurred. The continuation capture workaround (enter after 2+ days of sustained creation) is improbable because APs execute baskets immediately to minimize market risk.

**What would need to change:** Real-time or T+0 (same-day close, published before next open) ETF shares outstanding data would need to be available for free. This requires either: (a) ETF issuers accelerating their reporting timelines (unlikely — there is no regulatory or commercial incentive), or (b) a third-party data provider computing real-time ETF flow estimates from intraday creation/redemption activity (technically feasible but would be a paid product, not free).

**What-If Analysis:** With real-time data, the hypothesis becomes viable. The liquidity-mismatch mechanism is economically sound — ETF creation does create mechanical demand for small constituents, and that demand can move prices (Edge: 5). The LLM's format-standardization role (parsing heterogeneous holdings disclosures) is genuinely valuable (Novelty: 6). The strategy is capacity-constrained (small per-trade size), which is a feature for retail durability (Persistence: 5, Feasibility: 6). However, the in-kind vs. cash creation distinction remains a confound (Robustness: 4), and the backtesting challenge (historical intraday data for small constituents) is significant (Testability: 5).

**Research direction:** Monitor whether ETF issuers or aggregators (ETF.com, ETF Database) begin offering same-day shares outstanding estimates. This is a data infrastructure problem, not a conceptual one — the hypothesis could become viable if the data ecosystem evolves.

---

### K4: A4-H3 (original) — Post-FOMC Divergence Resolution (What-If: 5.00)

**Fatal flaw:** With ~40-60 divergence events over 15 years, and after a training/validation/test split, the test set contains ~20-25 events. A single LLM misclassification changes the win rate by 4-5 percentage points. Statistical significance at p < 0.05 is impossible to achieve.

**What would need to change:** Either: (a) many more years of FOMC data (requiring patience — 15 more years of FOMC meetings would add ~120 meetings and ~40-50 more divergence events), or (b) expansion to multiple central banks (ECB, Bank of England, Bank of Japan) to multiply the event count by 4-5x. Both paths are slow.

**What-If Analysis:** With sufficient sample size, the cross-asset consistency check — determining which market (bonds or equities) is misinterpreting the Fed's message — is a genuinely novel idea (Novelty: 8). The retail feasibility is excellent (Feasibility: 7 — free data, 4-6 trades/year). However, the mechanism faces the "everyone already does this" problem: FOMC statements are the most parsed documents in global finance (Persistence: 6, but may already be priced). The concern classification is a high-stakes task that even experienced Fed watchers get wrong (Robustness: 3). And the edge itself, even if real, is moderate (Edge: 5 — 1.5% per trade on 4-6 trades/year).

**Research direction:** The rescoped version (A4-H3-Revised, Factor Regime Classification) partially addresses the sample size issue by moving from event-level to quarter-level analysis. The original event-driven version should be archived and revisited in 10-15 years when more FOMC data has accumulated.

---

### K5: A4-H2 — Commodity Cost Transmission (What-If: 4.70)

**Fatal flaw:** Three compounding problems: (1) sector beta likely explains most of the variance in stock reactions to commodity moves, (2) 10-K sensitivity data is 6-9 months stale by the time commodity shocks hit, and (3) algorithmic traders price commodity-equity correlations in seconds, eliminating any multi-day delay.

**What would need to change:** A real-time, company-specific commodity sensitivity database would need to exist. This would require either: (a) companies to report commodity sensitivity in real-time structured filings (extremely unlikely), or (b) a commercial data product that continuously updates company-level commodity exposure estimates (would be expensive and proprietary). Even with such a database, the transmission delay problem (algo traders pricing the correlation in seconds) would remain — the competitive advantage would need to come from superior sensitivity estimation, not from speed.

**What-If Analysis:** With perfect, real-time sensitivity data, the hypothesis improves but is still constrained. The mechanism — input costs affect earnings, and company-specific sensitivity is not captured by sector membership — is economically sound (Edge: 5). However, even with perfect sensitivity data, the transmission delay in modern electronic markets is likely seconds, not days (Persistence: 3 — the edge, if it exists, would be arbed almost immediately). The strategy would be straightforward to replicate once published (Persistence: 3). The retail feasibility is decent (Feasibility: 6 — daily commodity price checks, free equity data) and testability is good (Testability: 6 — clean long-short portfolio test).

**Research direction:** Limited. The three compounding problems are individually serious and collectively fatal. The hypothesis could be resurrected in a different form — perhaps as a quarterly factor (commodity-sensitive stock baskets rebalanced after 10-K filings) rather than an event-driven strategy. But the fundamental issue (transmission delays are too short in modern markets) remains.

---

### K6: A6-H1 — Dealer Gamma Imbalance (What-If: 3.50)

**Fatal flaw:** Structural asymmetry in information and speed between options market makers (real-time position data, co-located execution) and a retail trader (stale end-of-day OI data, next-day limit orders). Attempting to front-run market makers at their own game using their own stale data is the "Wisdom of the Amateur" fallacy.

**What would need to change:** A retail trader would need either: (a) real-time options flow and OI data (which costs $10K+/year and is still slower than market makers' own systems), (b) direct market access with co-located servers (structurally impossible for retail), or (c) a fundamentally different source of advantage — perhaps combining the gamma calculation with a signal that market makers do NOT have, rather than trying to beat them at their own game. None of these pathways is realistic for retail.

**What-If Analysis:** Even with real-time data, this hypothesis is constrained. The gamma-flip magnet effect, if it exists, is well-understood by the market makers whose hedging creates it (Persistence: 2 — would be arbed almost immediately). The edge per trade is thin (Edge: 4 — 25bps target before costs). The LLM news filter is a genuine contribution (Novelty: 5) but doesn't change the fundamental structural disadvantage. The strategy requires intraday monitoring and execution (Feasibility: 3), which is incompatible with a once-per-day retail workflow. The one bright spot is testability (Testability: 5 — clean falsifiable prediction, low backtest costs), but the low expected returns after transaction costs make even a positive backtest unlikely to translate to live trading.

**Research direction:** None. The structural asymmetry is fundamental and cannot be resolved by better methodology. This hypothesis is the clearest case of a theoretically interesting idea that is structurally unexecutable for retail. The LLM's role as a context filter (news classification) is genuinely valuable, but it should be applied to hypotheses where the retail trader is NOT competing directly with the most sophisticated, fastest, and best-informed participants in financial markets.

---

## 6. STAGE 1 SELF-ASSESSMENT

### 6.1 What the Process Did Well

1. **The 5-round structure effectively filtered hypotheses.** Round 1 (generation) produced 21 hypotheses across 7 domains with well-specified mechanisms, data requirements, and falsifiable predictions. Round 2 (skeptic review) challenged every hypothesis systematically and identified 6 existential pre-tests. Round 3 (debate) produced meaningful revisions — agents conceded weaknesses, added controls, and merged overlapping hypotheses. Round 4 (final verdicts) applied a high bar — 26.3% PROMOTE rate, within the 20-40% target. Round 5 (this synthesis) provides a quantitative framework for prioritizing the survivors. This is a substantially better filtering process than a single-stage generation or a simple "rank these ideas" prompt.

2. **The cross-agent interaction produced genuinely emergent ideas.** The merged ACF hypothesis (consensus fragility measured at two points in the earnings cycle) and the synthesized CTDS hypothesis (CDS widening without linguistic adaptation as a divergence signal) could NOT have been produced by any single agent working alone. These are the most novel ideas in the set and they required the multi-agent debate structure to emerge. This validates the core premise of the 17-agent investigation: that LLMs embodying different domain expertise can produce ideas that transcend any single domain.

3. **The pre-test specification is a valuable methodological innovation.** Rather than building full backtesting pipelines for all 21 hypotheses (which would be extremely costly), the process identified 6 cheap, high-value pre-tests that resolve existential questions first. The total cost of all six pre-tests is $55-95 in API calls and 46-59 hours of data collection — a fraction of what full backtesting would cost. This "gate before you build" approach should be preserved in Stage 2.

4. **The "biggest weakness" self-assessment by agents was honest and accurate.** In almost every case, the fatal flaws that ultimately killed hypotheses were identified by the originating agents themselves in Round 1. The Skeptic's role was to validate, sharpen, and occasionally re-interpret these weaknesses, not to discover them de novo. This suggests the agent prompting produced appropriately self-critical reasoning.

5. **The re-scoping pattern (negative screening over directional betting) is a durable insight.** Agent 2 H3's transformation from an uneconomical directional short strategy to a viable negative screening tool is a template that could be applied to other moderate-precision signals. The recognition that not all predictive signals are tradeable — and that screening is a legitimate and valuable deployment — is an important methodological contribution.

### 6.2 What the Process Missed

1. **No hypothesis addresses portfolio-level interaction effects.** All 16 surviving hypotheses are evaluated as standalone signals. The correlation matrix of signal returns has not been estimated. Two hypotheses that both predict short-term negative returns after earnings calls (A1-H1 Pronoun Divergence and ACF Analyst Consensus Fragility) may have high signal correlation, reducing the diversification benefit of running both. This is flagged as an open question for Stage 2 but was not addressed in Stage 1 by design.

2. **No hypothesis was contributed by or evaluated by a "practitioner" agent.** All 7 generative agents represent different research domains (linguistics, accounting, narrative economics, cross-asset, alternative data, microstructure, behavioral finance). None represents the perspective of a retail trader who has actually attempted to implement and live-trade systematic strategies with $50K-$250K. A "Practitioner" agent in Stage 2 would bring practical constraints (broker API limitations, tax implications of high turnover, psychological challenges of drawdowns) that the current agents may underestimate.

3. **The scoring rubric weights may not reflect actual retail trader preferences.** The rubric weights Edge Magnitude and Persistence at 25% each, but a retail trader with limited capital and a finite trading career may value Edge Magnitude more highly (they need returns sooner) and Persistence less (they don't have a 10-year horizon). Conversely, a trader who wants a "set and check once a month" strategy may value Retail Feasibility far above the 10% weight. The weights are reasonable for an academic ranking but should be customized for individual trader circumstances in Stage 2.

4. **The process did not generate hypotheses in certain potentially fertile domains.** Notable gaps include: (a) no hypothesis uses insider transaction data (Form 4 filings) — a well-known source of predictive signal that an LLM could enhance by reading the footnotes explaining transaction purpose, (b) no hypothesis uses patent or intellectual property data (USPTO) — an LLM could classify patent quality, competitive positioning, and technology trajectory from patent text, (c) no hypothesis uses macroeconomic nowcasting from unstructured central bank speeches and minutes beyond the narrow FOMC focus, and (d) no hypothesis addresses the SPAC/de-SPAC lifecycle, which has been a rich source of retail-tradeable anomalies. These gaps reflect the domain coverage of the 7 selected agents, not a judgment that these domains are infertile.

5. **The process did not include a formal "red team" attempt to generate the NULL distribution.** The Skeptic's role was adversarial review, not null hypothesis generation. A formal exercise where agents are asked "assume the null hypothesis — all these signals are fake — what patterns would we observe that could be mistaken for real edges?" would calibrate expectations and potentially reveal statistical pitfalls before backtesting.

### 6.3 What Biases May Remain

1. **Survivorship bias in hypothesis generation.** All 7 agents developed their hypotheses using knowledge of US public companies that exist today and have survived. The historical data on which these hypotheses will be tested contains companies that failed, were acquired, or went bankrupt — but the hypothesis mechanisms were not stress-tested against survivorship. For example, the Management Credibility Trajectory hypothesis would have given high credibility scores to Enron's management in 1999-2000 (they consistently "beat" guidance before the fraud was revealed). The hypotheses implicitly assume the mechanisms are stationary across the survival and failure of companies.

2. **Overconfidence from structured falsification.** The falsifiable predictions are specific and quantitative, which creates an illusion of rigor. But the predictions were generated by the SAME agents who generated the hypotheses — they have not been independently reviewed for whether the quantitative thresholds (200bps, 60% hit rate, 2.5x lift) are calibrated to realistic effect sizes or whether they are set at levels that the agents believe will produce "passing" results. An independent calibration of minimum detectable effects from the data (power analysis) would be more trustworthy.

3. **Narrative coherence bias.** Hypotheses that tell a clean, compelling causal story (FDA reviewers encode skepticism through language -> predict CRLs) score higher on the rubric than hypotheses that are messy or conditional (supply chain shock transmission -> depends on name resolution AND C-F decay AND liquidity constraints). The rubric does not penalize narrative simplicity, but financial markets reward ideas that capture complex, multi-conditional realities. The top-ranked hypothesis (FDA) is genuinely strong, but its top position is partially attributable to how cleanly the mechanism maps to a single data source with binary outcomes.

4. **Domain representation bias in the scoring.** The PROMOTE list overweights hypotheses that use SEC EDGAR filings (A1-H1, A2-H2, A2-H3, A3-H3). This is not a coincidence — the facilitator shares the agents' comfort with text-based analysis. Hypotheses that require non-text data (options flow, ETF flow, commodity prices) scored systematically lower, partially because the agents and reviewer are more skeptical of non-text signals, and partially because non-text data for retail traders genuinely has worse accessibility and timeliness. But the text-centricity of the PROMOTE list may reflect shared disciplinary bias as much as objective quality.

5. **In-sample optimization of the scoring rubric itself.** The 6 dimensions and their weights were specified before scoring, but they were designed with knowledge of the 21 hypotheses. Dimensions that favor text-based, archival-data hypotheses (Testability, Persistence) received higher weights (15%, 25%) than dimensions that favor real-time, event-driven hypotheses (Edge Magnitude also at 25% but harder to score highly on for text-based signals). A different rubric — one that weighted "capacity for scale" or "immunity to crowding" more heavily — would produce a different ranking. The rubric is reasonable but not objective.

6. **The "what-if" scores for KILLED hypotheses are systematically optimistic.** The facilitator scored KILLED hypotheses assuming their fatal flaw was magically fixed, but did not account for the possibility that FIXING the fatal flaw would introduce new problems. For example, the Hesitation-Cluster hypothesis "what-if" assumes verbatim transcripts — but if verbatim transcripts existed, they might be so noisy (filled pauses are ubiquitous in normal speech) that the signal-to-noise ratio collapses. The "what-if" scores should be interpreted as upper bounds, not realistic counterfactuals.

7. **No market efficiency prior was explicitly modeled.** The scoring implicitly assumes that markets are inefficient enough for these edges to exist. A Bayesian approach that starts with a skeptical prior (e.g., 90% probability that any given hypothesis has zero true edge) and updates based on the strength of the mechanism and data would produce more conservative scores. The current scores represent the "best case if the mechanism is real" rather than "expected value integrating over the probability that the mechanism is fake." For Stage 2 capital allocation, an explicit efficiency prior should be incorporated.

---

## 7. STAGE 2 RECOMMENDATIONS

Based on the ranking and analysis above, the following are recommended priorities for Stage 2:

### Immediate Backtesting Priority (Rank 1-3)

These hypotheses have the highest composite scores AND the fewest pre-test dependencies:

1. **A5-H1 (FDA Briefing Document Asymmetric Skepticism):** Data is fully archival and free. No pre-test gates. Start backtesting immediately on 2017-2022 training data.
2. **A2-H2 (CAM Expansion Velocity):** Data is fully archival and free. Requires CAM taxonomy construction (2-3 days of LLM processing) before backtesting. Start after taxonomy is built.
3. **A2-H3 (Departure Language Severity):** Data is fully archival and free. Requires departure event database construction. Start after event extraction pipeline is built.

### Pre-Test Resolution Priority (Rank 4-8)

These hypotheses have pre-test gates that must be resolved before backtesting:

4. **A1-H1 (Pronoun Divergence):** Phase 1 manual validation of transcript fidelity against audio recordings should be conducted first.
5. **ACF (Analyst Consensus Fragility):** Pre-Test 2 (analyst snippet detail) must be resolved before the merged framework can be backtested.
6. **A3-H3 (Management Credibility Trajectory):** End-to-end pipeline test on 20 companies before scaling to full universe.
7. **A5-H3 (App Store Review):** Pre-Test 4 (leading-vs-lagging timestamps) is the existential gate.
8. **CTDS (CDS-Transcript Divergence):** CDS data pathway must be resolved before any backtesting.

### Infrastructure Priority

Build the shared infrastructure components that serve multiple hypotheses:
- **10-K/10-Q ingestion and section extraction pipeline** (serves A1-H2, A2-H1, A2-H2, A2-H3, A4-H1, CTDS)
- **Transcript ingestion and speaker-segmentation pipeline** (serves A1-H1, A1-H2, A3-H1, A3-H3, ACF)
- **Embedding and semantic similarity computation pipeline** (serves A3-H1, A3-H2, A5-H1, ACF)
- **LLM classification API with structured JSON output** (serves all hypotheses)

### Portfolio Construction (After Backtesting)

Once individual hypothesis backtests are complete:
1. Estimate the correlation matrix of signal returns across the top 5-8 hypotheses
2. Allocate capital using a risk-parity or Kelly-optimal framework
3. Backtest the combined portfolio on the out-of-sample period
4. Assess live trading feasibility: data latency, execution costs, broker compatibility, time commitment

---

## 8. CONCLUSION

Stage 1 of the 17-agent investigation generated 21 original hypotheses across 7 domains. After 5 rounds of adversarial review, revision, merger, synthesis, and scoring, **6 hypotheses are PROMOTEd** to Stage 2 empirical testing and **10 are REVISEd** with specific changes required.

The PROMOTE list is concentrated in hypotheses that share three characteristics: (1) a genuine LLM measurement advantage that no existing system can replicate, (2) free, archival data that enables comprehensive backtesting without vendor dependency, and (3) holding periods of days to months that are executable by a retail trader checking once per day. These are the minimum requirements for a hypothesis to advance from idea to empirical validation.

The KILL list is concentrated in hypotheses that attempted to compete with institutional participants on speed (gamma hedging, ETF flow, commodity transmission) or that could not operate without data that exceeds retail budget (CDS, full analyst reports). The "Wisdom of the Amateur" fallacy — the idea that a retail trader can beat institutional participants at their own game using worse data — is the single most common failure mode.

The Stage 1 process demonstrated that a structured, multi-agent, multi-round adversarial framework can efficiently filter a large set of trading hypotheses, identify the strongest candidates, and produce a quantitative ranking that guides empirical prioritization. The surviving hypotheses represent the most promising candidates for LLM-based trading edge discovery — ideas that are novel enough to be unexploited, grounded enough to be plausible, and feasible enough to be testable by a retail trader.

**Stage 1 complete.** The investigation proceeds to Stage 2: Empirical Validation.

---

*Document generated by the Facilitator, Round 5 of 5, Stage 1 Synthesis and Ranking.*
*Hypotheses scored on the 6-dimension weighted rubric specified in the Stage 1 framework.*
*KILLED hypothesis "what-if" scores represent upper bounds assuming fatal flaw resolution without introducing new problems.*
