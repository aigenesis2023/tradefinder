# Agent 1: Earnings Whisperer — Round 1 Hypotheses

---

## HYPOTHESIS 1: The Pronoun Divergence Signal

**HYPOTHESIS NAME:** The Pronoun Divergence Signal

**SOURCE AGENT:** Earnings Whisperer

**MECHANISM:**
A statistically abnormal drop in first-person plural pronoun usage ("we", "us", "our") from prepared remarks to Q&A on financially material topics predicts negative earnings surprises over the subsequent 1-5 days. The causal chain: when executives possess undisclosed negative information, they unconsciously distance themselves from the bad news during unscripted Q&A by shifting from ownership language ("we decided to...") to depersonalized constructions ("the decision was made to...", "it was determined..."). Prepared remarks are vetted and polished, so the divergence only emerges under the cognitive load of spontaneous Q&A. This is a specific application of psychological distancing theory (Pennebaker, 2011) operationalized as a quantitative signal.

**LLM ADVANTAGE:**
An LLM enables three things no human or traditional NLP can do simultaneously: (1) topic-level segmentation of transcripts so pronoun ratios are computed per topic rather than per document (avoiding dilution from benign segments), (2) executive-specific baseline modeling — each CEO/CFO has their own historical pronoun-ratio distribution across quarters, and (3) scale — ~4,000 earnings calls per quarter across US equities. A human analyst cannot track 4,000 calls, and regex-based NLP cannot segment topics reliably or model individual executive baselines.

**WHY UNDERWEIGHTED:**
Three reasons: (a) The academic literature on pronoun shifting and deception exists (Larcker & Zakolyukina, 2012; Hobson et al., 2012) but has never been operationalized into a systematic, daily-actionable trading factor — it remains in accounting journals, not quant pipelines. (b) Market participants consume earnings calls for headline numbers (EPS beat/miss, guidance) and narrative summaries, not micro-linguistic pattern analysis. (c) The signal requires per-executive baseline modeling over 8+ quarters of history before it becomes reliable, which is computationally tedious and requires longitudinal data that most systematic funds don't curate at the transcript-linguistic level.

**HOLDING PERIOD:** 1-5 days (until the next material disclosure or price drift resolves)

**DATA REQUIREMENT:**
- SEC EDGAR 8-K filings (free) — earnings call transcripts filed as exhibits
- Seeking Alpha earnings call transcript pages (free tier, rate-limited but sufficient for daily checking)
- Financial Modeling Prep API (free tier: 250 calls/day, sufficient for historical financial data cross-reference)
- Yahoo Finance (free) for price data and earnings surprise history

**PROCESSING APPROACH:**
1. For each earnings call transcript, the LLM first segments the text into: (a) prepared remarks vs. Q&A, (b) individual executive speakers, (c) topic segments within each (revenue, margins, guidance, capex, competitive landscape, regulatory, etc.) using embedding-based semantic chunking.
2. For each topic segment spoken by each executive, compute the first-person plural ratio: PPR = count("we" + "us" + "our") / count(all pronouns including I/me/my/they/them/their/it/its).
3. For each executive, maintain a trailing 8-quarter distribution of their Q&A PPR per topic category. Flag any topic-segment where the executive's PPR drops below their personal 10th percentile for that topic.
4. Aggregate: a stock is flagged when either the CEO or CFO exhibits a significant PPR divergence (p < 0.10 relative to personal baseline) on a financially material topic (revenue, margins, or guidance).
5. Direction: short candidate. Exit after 5 trading days or on the next material 8-K filing, whichever comes first.

**FALSIFIABLE PREDICTION:**
If real, stocks flagged for significant pronoun divergence (bottom decile of executive's own historical PPR distribution on a material topic) should exhibit negative excess returns of at least **200bps** relative to the S&P 500 over the subsequent 5 trading days, statistically significant at p < 0.05 after multiple-comparison correction. If fake, flagged stocks show returns indistinguishable from zero excess return (mean excess return between -50bps and +50bps, p > 0.10). Additionally, the effect should be asymmetric — pronoun *increases* (above 90th percentile) should NOT predict positive excess returns, because psychological distancing is a unidirectional signal of concealment, not enthusiasm.

**MINIMUM EFFECT SIZE:** 150bps excess negative return over 5 days, net of 50bps estimated transaction costs (slippage + borrow for shorting mid-cap names).

**OUT-OF-SAMPLE PLAN:**
- **Training:** Build executive baseline distributions using 2021-2023 Q1-Q4 earnings call transcripts (12 quarters per executive minimum).
- **Validation:** Test PPR divergence thresholds on 2024 Q1-Q3 calls. Optimize the percentile cutoff (try 5th, 10th, 15th, 20th) on validation set only.
- **Out-of-sample test:** Apply the fixed threshold to 2024 Q4 and 2025 Q1 calls. Report both raw returns and risk-adjusted alpha (Fama-French 3-factor).
- **Walk-forward:** Re-estimate executive baselines quarterly using expanding windows. Monitor signal decay over calendar time.

**SELF-ASSESSED CONFIDENCE:** Medium

**BIGGEST WEAKNESS:**
(1) Some executives have naturally high pronoun-use variance due to personality or cultural factors — the baseline model may be noisy for executives with fewer than 8 quarters of history. (2) Exogenous events (industry consolidation, regulatory changes, M&A) can cause legitimate pronoun shifts that are not deceptive — e.g., an acquired company's CEO saying "they" when referring to the acquirer's decisions is truthful, not evasive. The topic segmentation may not perfectly distinguish these cases. (3) Transcript providers sometimes normalize or paraphrase Q&A, which could strip or alter pronoun patterns — fidelity to the original spoken word varies by data source.

---

## HYPOTHESIS 2: The Scripted-Answer Echo Detection

**HYPOTHESIS NAME:** The Scripted-Answer Echo Detection

**SOURCE AGENT:** Earnings Whisperer

**MECHANISM:**
Q&A responses that are linguistically more similar to the company's SEC filing prose (10-K/10-Q) than to conversational speech predict a higher probability of negative earnings surprises in the following quarter. The causal chain: when management has material negative information they wish to obscure, IR/legal teams pre-draft Q&A answers using the same formal, defensive language found in SEC filings. This produces a detectable "filing echo" — Q&A answers that carry the lexical density, syntactic complexity, hedging constructions, and boilerplate of legal/financial writing rather than the lower lexical density, simpler syntax, and personal constructions of spontaneous speech. Pre-scripted answers are a behavioral marker of active narrative management, which correlates with information suppression.

**LLM ADVANTAGE:**
An LLM is uniquely capable of computing deep semantic and stylistic similarity between Q&A utterances and SEC filing prose because: (a) embedding models capture paragraph-level semantic similarity that bag-of-words and TF-IDF cannot, (b) LLMs can separately measure stylistic dimensions (formality, hedging density, passive-voice ratio, sentence length distribution) and compare them to both filing baselines and conversational baselines, (c) the LLM can distinguish "this sounds like the risk factors section" from "this sounds like the MD&A," providing nuance on *which part* of the filing is being echoed. Traditional NLP cannot capture the multi-dimensional stylistic fingerprint needed.

**WHY UNDERWEIGHTED:**
(a) Most quantitative earnings-surprise models use financial statement data (accruals, earnings quality), analyst estimates, and price momentum — linguistic style analysis of Q&A is absent from factor libraries. (b) The signal requires processing both lengthy SEC filings (~50K-150K words per filing) and transcripts simultaneously, which is computationally intensive with traditional methods. (c) Analysts focus on *what* was answered, not *how* it was answered — detecting scriptedness requires comparing the answer's linguistic form to two separate corpora (filings and conversational baselines), which no sell-side research product does.

**HOLDING PERIOD:** 1-4 weeks (through the next quarterly earnings announcement or pre-announcement)

**DATA REQUIREMENT:**
- SEC EDGAR (free) — 10-K and 10-Q filings, 8-K earnings call transcripts
- Seeking Alpha earnings transcripts (free tier) for alternate transcript source
- Yahoo Finance (free) for price data, earnings dates, and consensus estimates
- Earnings surprise data from Financial Modeling Prep API (free tier) or Nasdaq.com (free)

**PROCESSING APPROACH:**
1. For each company, build a "filing corpus" from the most recent 10-K and 10-Q (full text, split by section: Risk Factors, MD&A, Financial Statements, Notes, Legal Proceedings).
2. Build a "conversational baseline corpus" from unscripted Q&A across all companies in different sectors (to capture genuine spoken financial English without company-specific contamination). Filter to Q&A segments where the analyst question is genuinely challenging (not a softball) based on question length and directness markers.
3. For each Q&A response in the target company's earnings call, embed the answer text and compute:
   - **Filing Similarity (FS):** cosine similarity between the Q&A answer embedding and the company's own filing corpus embeddings (max over all filing sections).
   - **Conversational Similarity (CS):** cosine similarity between the Q&A answer embedding and the cross-company conversational baseline embeddings (mean of top-10 matches).
   - **Scripting Quotient (SQ):** SQ = FS / CS. Higher SQ means the answer is closer to formal filing prose than to natural Q&A speech.
4. Aggregate to company-call level: take the 75th percentile SQ across all Q&A responses as the company's scripting score for that call.
5. Flag companies in the top decile of SQ (SQ > 2.0) as "highly scripted." Direction: short candidate or avoid long.

**FALSIFIABLE PREDICTION:**
If real, top-decile SQ companies should exhibit a negative earnings surprise rate (actual EPS < consensus by >1 standard deviation of analyst estimates) that is at least **2.0x** the rate of bottom-decile SQ companies in the subsequent quarter. Baseline unconditional negative-surprise rate is approximately 20-25%; the top-decile rate should be ~40-50%, while bottom-decile should be ~15-20%. If fake, negative surprise rates are statistically uniform across SQ deciles (chi-squared test p > 0.10).

**MINIMUM EFFECT SIZE:**
A 1.8x lift in negative-surprise probability relative to unconditional rate (i.e., from ~22% to ~40%), which translates to approximately 300bps of avoidable negative drift per flagged position (assuming a -6% average move on negative surprise, avoided 40% of the time vs. 22% baseline).

**OUT-OF-SAMPLE PLAN:**
- **Training:** Compute SQ distributions and calibrate the 75th-percentile aggregation on 2021-2022 earnings calls (8 quarters). Use these periods to also build the conversational baseline corpus.
- **Validation:** Test SQ thresholds on 2023 Q1-Q4. Determine optimal SQ cutoff (>2.0, >2.5, >3.0) and optimal aggregation percentile on validation set.
- **Out-of-sample test:** Apply the fixed model to 2024 Q1-Q4 earnings calls. Evaluate: does top-decile SQ in quarter T predict negative surprise in quarter T+1 with the claimed effect size?
- **Robustness checks:** (a) Control for industry fixed effects (some sectors naturally have more formal Q&A). (b) Control for company size (large caps may have more scripted IR). (c) Test whether the signal works on the *same* quarter's surprise or only the *next* quarter's.

**SELF-ASSESSED CONFIDENCE:** Medium-High

**BIGGEST WEAKNESS:**
(1) Some companies with excellent, transparent IR practices may produce high-SQ answers because they prepare thoroughly — not to conceal, but to be precise. This creates false positives. (2) CEO personality is a major confound: some CEOs naturally speak in formal, structured language even when unscripted (common in legal/finance-background CEOs). Without per-CEO baseline modeling (analogous to Hypothesis 1), the SQ may flag communication style rather than concealment intent. (3) The signal may work primarily on mid-cap and small-cap companies where IR resources are thinner and the difference between spontaneous and scripted Q&A is starker — large-cap companies may have uniformly high SQ (always scripted), making the signal useless for the most liquid names.

---

## HYPOTHESIS 3: The Hesitation-Cluster Anomaly

**HYPOTHESIS NAME:** The Hesitation-Cluster Anomaly

**SOURCE AGENT:** Earnings Whisperer

**MECHANISM:**
When C-suite executives across multiple companies in the same industry exhibit simultaneous, above-baseline hesitation markers (filled pauses, self-corrections, false starts, abnormally long response latencies) on semantically similar topics, it predicts sector-level underperformance over the following 1-4 weeks. The causal chain: an industry-wide disruption (technological shift, regulatory change, demand inflection, supply-chain shock) arises that management teams have not yet fully quantified or understood. During Q&A, when pressed on the disruption topic, executives across different companies exhibit genuine cognitive struggle — hesitating, self-correcting, and restarting sentences — because they are actively processing the information in real time. This is not "negative sentiment"; it is a raw cognitive signal of uncertainty. The cross-company clustering distinguishes an industry-wide shock (many companies hesitating on the same topic) from idiosyncratic executive nervousness (one CEO who always says "um").

**LLM ADVANTAGE:**
An LLM enables a multi-stage pipeline that no traditional method can replicate: (a) hesitation detection from transcripts (many transcript services strip fillers, so the LLM must infer hesitation from self-corrections, false starts, and sentence fragments that survive cleaning), (b) extraction of the *semantic topic* being discussed during each hesitation event (the 50-word context window around the hesitation), (c) embedding-based clustering of hesitation topics *across companies* to detect when 5+ companies in the same sector hesitate on semantically related concepts within a 2-week earnings window. Traditional NLP cannot do cross-document topic clustering of this granularity; bag-of-words would miss that "tariff exposure in Southeast Asia" and "supply chain relocation costs" are the same underlying topic.

**WHY UNDERWEIGHTED:**
(a) No existing quant factor measures industry-level cognitive disruption from linguistic data — sector momentum, earnings revision breadth, and macro surprise indices exist, but none capture management's real-time struggle to process new information. (b) The signal requires cross-company analysis at earnings-season scale (~500+ calls in a peak week), which is computationally prohibitive without LLMs. (c) Hesitation research exists in psycholinguistics but has never been applied to cross-sectional equity trading — it's an entirely novel factor class. (d) The signal fires rarely (perhaps 2-4 times per year) and requires patience, which systematic funds with monthly rebalance schedules may not accommodate.

**HOLDING PERIOD:** 1-4 weeks (time for the sector disruption to filter into analyst estimates and institutional positioning)

**DATA REQUIREMENT:**
- SEC EDGAR 8-K transcripts (free) — need timestamped or verbatim transcripts that preserve hesitation markers
- EarningsCast (free tier) or company IR websites for raw audio replays (to verify hesitation markers stripped from text transcripts)
- Seeking Alpha transcripts (free tier) as secondary source; compare with EDGAR for transcription fidelity
- Yahoo Finance (free) for sector ETF prices and S&P 500 benchmark
- Finviz (free screener) for sector/industry classification mapping

**PROCESSING APPROACH:**
1. **Hesitation Detection:** For each earnings call transcript, the LLM scans Q&A responses for five categories of hesitation markers: (a) filled pauses ("um", "uh", "er" — if preserved in transcript), (b) self-corrections ("I mean—", "wait, let me rephrase", "actually, no"), (c) false starts (sentence fragments that restart), (d) hedge clusters (3+ hedging phrases within one sentence window: "sort of", "to some extent", "it depends", "hard to say"), (e) question-evasion markers (the executive asks for the question to be repeated, gives a non-answer, or pivots to a different topic entirely). Each hesitation event is tagged with its 50-word context window.
2. **Topic Extraction:** The context window around each hesitation event is embedded. The LLM extracts a short topic label (5-10 words) summarizing what was being discussed.
3. **Cross-Company Clustering:** Within a rolling 2-week earnings window, all hesitation-topic embeddings across all reporting companies are clustered using cosine similarity (threshold: 0.80). A cluster is "significant" if it contains hesitation events from at least 5 different companies spanning at least 2 sub-industries within the same GICS sector.
4. **Baseline Comparison:** Historical cluster sizes (by sector and week) are computed over the trailing 3 years. A cluster is "anomalous" if its size exceeds the 95th percentile of historical cluster sizes for that sector and calendar quarter.
5. **Signal:** When an anomalous hesitation cluster fires for a sector, flag the sector for underperformance. Direction: short the sector ETF (e.g., XLE, XLK, XLF) or go long put options. Exit after 3 weeks or on the cluster's topic appearing in mainstream financial news headlines (indicating the disruption is now publicly priced).

**FALSIFIABLE PREDICTION:**
If real, when a sector-level anomalous hesitation cluster fires (size > 95th percentile, 5+ companies, 2+ sub-industries), the equal-weighted sector ETF should underperform the S&P 500 by at least **300bps** over the subsequent 3 weeks, with the signal firing at least 2 times per year on average. If fake, post-cluster-fire sector ETF returns relative to SPY are indistinguishable from zero (mean excess return between -100bps and +100bps, p > 0.15 on a t-test of all cluster-fire events).

**MINIMUM EFFECT SIZE:**
200bps sector underperformance over 3 weeks, net of 50bps ETF short costs (borrow + slippage on liquid sector ETFs). At $100K position size, this is $2,000 of excess return per fire event.

**OUT-OF-SAMPLE PLAN:**
- **Phase 1 (Hesitation Detection Calibration):** Manually annotate 100 earnings call transcripts for hesitation events to validate LLM detection accuracy against human judgment. Tune detection prompts to achieve >80% recall and >70% precision on hesitation markers.
- **Phase 2 (Baseline Construction):** Build the historical cluster-size distribution using 2021-2023 earnings call transcripts. Establish sector-by-quarter cluster-size percentiles.
- **Phase 3 (Validation):** Run the full pipeline on 2024 Q1-Q3 earnings seasons without looking at returns. Freeze the cluster-size threshold (95th percentile). Then evaluate returns for all cluster-fire events in 2024 Q1-Q4.
- **Phase 4 (Live Test):** Run the pipeline in "shadow mode" during 2025 Q1-Q2 earnings season. Record signals but do not trade. Compare predicted vs. actual sector returns. Only go live when shadow-mode results match validation performance.

**SELF-ASSESSED CONFIDENCE:** Low-Medium

**BIGGEST WEAKNESS:**
(1) **Transcript fidelity is the Achilles' heel.** Most free transcript sources (Seeking Alpha, Motley Fool, even some EDGAR filings) are cleaned and edited — hesitation markers are systematically stripped. The signal may require raw audio processing (Whisper-based transcription with hesitation preservation), which is computationally expensive and adds latency. Without verbatim transcripts, the hesitation detection step fails entirely. (2) **Signal sparsity.** A genuine cross-company hesitation cluster may fire only 2-4 times per year, making statistical validation difficult with limited sample sizes. The out-of-sample test may have only 3-6 events, yielding wide confidence intervals. (3) **Confounding by macro events.** FOMC meetings, geopolitical shocks, and natural disasters can cause correlated hesitation across sectors that is not a tradable "edge" — everyone is uncertain, and the market prices macro uncertainty quickly. The signal must distinguish industry-specific cognitive disruption from general macro anxiety. (4) **Executive speech diversity.** Some cultures and personality types use filled pauses as a normal speech pattern (e.g., "um" is more common in certain regional dialects). Without per-executive baseline normalization (analogous to H1), the cross-sectional comparison is noisy.

---

## Cross-Hypothesis Notes

**Complementarity:** These three hypotheses target different timescales and different parts of the earnings cycle. H1 (Pronoun Divergence) is a near-term tactical signal firing immediately after an earnings call. H2 (Scripted-Answer Echo) is a medium-term signal that predicts the *next* quarter's surprise. H3 (Hesitation Cluster) is a sector-level signal that fires during earnings season peaks. They can be combined into a multi-horizon framework: H1 for 1-5 day tactical shorts, H2 for 1-4 week position shorts, H3 for sector-hedging overlays.

**Data Synergies:** All three hypotheses share the same core data infrastructure (SEC EDGAR transcripts + Seeking Alpha + Yahoo Finance). Building the transcript ingestion and LLM processing pipeline once serves all three signals, reducing marginal cost per hypothesis.

**Execution Feasibility for Retail Trader ($50K-$250K):** All three signals require checking once per day (post-market after earnings calls are released, typically by 6pm ET). A retail trader can run the LLM pipeline overnight or early morning, review flagged names, and place orders during regular market hours. Positions are held for days to weeks, not minutes, so intraday execution is not required. Short exposure can be achieved via inverse ETFs or put options for traders without margin accounts.

**LLM Cost Estimate:** Processing ~4,000 earnings calls per quarter requires approximately 12,000 LLM API calls (3 passes per transcript: segmentation, pronoun/scripting analysis, hesitation detection). At current API prices (~$0.01-0.03 per call for a capable model), the quarterly cost is approximately $120-360 — well within a retail trader's budget.
