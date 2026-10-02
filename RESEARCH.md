# Trading-Bot Research: What Could Actually Work for a Retail Systematic Bot

**Mission date:** 2026-10-01/02
**Method:** three parallel deep-research tracks (public web: fee schedules, academic papers, practitioner repos, Bloomberg/WSJ reporting). Every angle was investigated with intent to kill it. Claims carry sources or numbers; where evidence was absent, that is stated.
**Prior art:** v1–v6 of the ensemble crypto paper-trading bot (see VERSION_LOG.md). All died. Binding constraints established: (1) retail taker fees (~50bps/side) create $50–100/trade drag against $100 risk — fees ate ~96% of gross on minute bars; (2) gross edges do not survive walk-forward out-of-sample; (3) naive maker execution dies of adverse selection (24% win rate — fills arrive exactly when price moves through).

**Scope exclusions (not re-investigated):** generic momentum/mean-reversion on majors (proven dead in v1–v6), grid bots, martingale, copy-trading, signal-selling.

---

## Ranked angles (best first)

### 1. Long-only swing trend-following on BTC/ETH spot — MARGINAL, ~30%

**Edge hypothesis (plain English):** Financial markets trend more than a random walk would — sustained moves persist because of slow information diffusion, herding, and risk-management flows. A system that buys breakouts and rides them for weeks, cutting losers quickly, harvests this. The money comes from the minority of large trends paying for many small whipsaw losses.

**Why it might survive where v1–v6 died:** the fee problem genuinely disappears. At a 15% target move, a 1% round-trip fee is ~6.7% of a win's gross (~27% of expected gross at 50% win rate) vs ~96% on minute bars. Fees go from binding constraint to rounding error.

**Documented evidence (strongest of anything surveyed):**
- Moskowitz–Ooi–Pedersen (2012): time-series momentum across 58 liquid futures, ~Sharpe 1.0.
- Hurst–Ooi–Pedersen, "A Century of Evidence on Trend-Following Investing" (2017): 67 markets, 1880–2016, **net-after-costs 11.2%/yr at 9.7% vol**, positive in every decade, positive in 8 of 10 worst 60/40 crises. The most replicated finding in systematic finance.
- Crypto-specific: Liu–Tsyvinski (1–4-week crypto momentum); Han–Kang–Ryu (SSRN 4675565): time-series momentum survives realistic costs (cross-sectional does not — it needs shorting).
- Reality check on advertised numbers: artursepp's `trendfollowingsystems` repo finds net Sharpes of 0.47–0.55 vs ~1.0 in papers; **AQR's own forward assumption is 0.4**. Expect roughly half the paper edge.
- Live analog: Bitwise Trendwise ETFs (10/20-day EMA on BTC, live since Dec 2024): lost 11–15% over a year BTC lost 32% — drawdown mitigation, not consistency.

**Difficulty / capital / infrastructure:** Honest. Capital: $50–500 works mechanically (fractional spot), but you can't diversify across 2 assets the way the papers' 67-market portfolios do — single-name trend means binary outcomes per cycle. Infrastructure: trivial — daily bars, no speed needs. The real costs are psychological and temporal (below).

**Probability assessment: ~30%** that a competent, patient retail operator runs this profitably net of fees over a full cycle.

**The catches (why only 30%):**
- **Validation takes years.** Sharpe statistics: distinguishing Sharpe 0.5 from zero at 95% confidence needs ~16 years of data (t = S√T). At 4–15 trades/yr/asset, three years of live trading gives ~30 trades — you cannot tell a 50% system from a 55% system for years. Every parameter tweak restarts the clock. This is where retail operators fool themselves.
- **Drawdowns are career-threatening.** Trend followers routinely eat 20–30%+ drawdowns; multi-year flat periods ("CTA winter" 2010s). On 2 concentrated crypto assets, worse.
- **Long-only halves the evidence.** The academic results are long-short; US retail can't easily short spot crypto, so you keep ~half the return and eat every bear market in full.
- **Edges decay:** funding-carry Sharpe went 6.45 (2020–25) → 4.06 (from 2024) → negative in 2025 (Borri et al.). Trend is too capacity-rich to die, but forward edge < historical edge.

**What validation would look like:** build on daily bars (free data to 2010 via CoinMetrics Community API), walk-forward with the existing framework, deflated Sharpe across all variants tried, then live paper for 12+ months minimum before any conclusion. Kill criteria set in advance. Realistic expectation: net Sharpe 0.4–0.8, 8–15%/yr at 20–25% vol target, 15–25% drawdowns.

---

### 2. Kalshi far-OTM tail-selling (short-dated binaries) — MARGINAL, ~20%

**Edge hypothesis:** Sellers of far out-of-the-money binary contracts harvest the variance-risk premium — buyers systematically overpay for lottery tickets (favorite-longshot bias, documented on Kalshi by GWU 2026-001). You collect small premiums; most expire worthless in your favor.

**Why it might survive:** the one sub-angle that doesn't compete on latency. Fees are tiny at 10–20¢ prices (~0.2–0.4¢/contract), and as a maker on standard Kalshi markets the fee is **$0**. No speed race — you're warehousing risk, not reacting.

**Documented evidence:** GWU 2026-001 documents systematic longshot overpricing on Kalshi with "modestly positive" returns on expensive contracts (the mirror image: shorting cheap longshots). Favorite-longshot bias is one of the oldest documented anomalies in betting markets generally. Counter-evidence: the bias is now *published*, which starts the decay clock; and one practitioner's census shows subsidy yields on Kalshi decay 119× within days of programs launching.

**Difficulty / capital / infrastructure:** Medium. Kalshi has an official REST+WebSocket API (docs.kalshi.com), RSA-PSS auth, adequate rate limits. US account needs 18+, KYC (gov ID + SSN); California is eligible. $50–500 can get fills (thin books are $50–200/side). The real difficulty is risk management, not tech.

**Probability assessment: ~20%.**

**The catches:** you're warehousing unhedgeable tail risk — one unexpected event wipes out months of premium collection. This is "picking up pennies in front of a steamroller" unless position sizing is ruthlessly small (fractional Kelly on tail risk is unforgiving). Unproven at retail scale; no documented profitable retail operator found. Adverse selection measured by a real practitioner: +1¢ gross → **−8.6¢ realized** on weather market-making — your fills come from informed flow.

**What validation would look like:** 4–6 weeks of maker-only paper quoting on thin, slow books via the free Kalshi API, simulating fills with the measured adverse-selection haircut (−8.6¢/contract, not gross). Kill criteria: negative net-of-fees P&L after 500+ fills. Benchmark against the naive alternative (just buying 90¢ favorites per GWU's bias finding) — your cleverness must beat the dumb version.

---

### 3. Kalshi–Polymarket complementary-pair arb — MARGINAL, ~25%

**Edge hypothesis:** the same event is sometimes priced differently on two venues. Buy YES where cheap, buy NO where NO is cheap (or the equivalent complementary pair); hold to settlement; exactly one side pays $1. The money comes from venue disagreement, not prediction.

**Why it might survive:** cleanest settlement mechanics of anything surveyed — binary, hold-to-expiry, no path dependency. Kalshi maker leg is $0 fee on standard markets. A University of Toronto / HEC Montréal / ESSEC paper found within-market arb trades systematically exploitable at 1–5%.

**Documented evidence:** the arb structure is real and studied, but the practitioner repos found (`realfishsam`, `CarlosIbCu`, `jho1019`) are scannerware — alert-only or dry-run, none with audited live P&L. Meanwhile ~5% of bot-like wallets generate 75% of Polymarket volume and **823 accounts netted >$100K each** (Bloomberg) — the winners are professionalized operations.

**Difficulty / capital / infrastructure:** Medium-high. Polymarket global is **geo-blocked for US users**; Polymarket US (0.30% taker / 0.20% maker rebate) is now past waitlist but sports-focused and mobile-only — API access uncertain. USDC (Polygon) vs USD settlement-currency mismatch, ACH withdrawal delays, and **resolution-rule mismatch between venues** (the "same" event can resolve differently — unhedgeable leg risk). Capital locked on both sides until resolution.

**Probability assessment: ~25%.**

**The catches:** opportunities are 1–5% gross, seconds-lived, contested by professional bot operations. Kalshi taker at 50¢ is 3.5% of price — one taker leg eats a typical 3% spread whole, so the viable structure is maker-on-Kalshi (fill uncertainty + adverse selection) hedged on Polymarket. Your realistic harvest is scraps. Fee math: survives only via the $0 maker leg.

**What validation would look like:** run an alert-only scanner for 30 days logging gross spread × size × frequency net of the real Kalshi fee formula (`ceil(0.07 × P × (1−P))`), before committing a dollar. Manually verify resolution-rule equivalence per event. Kill criterion: fewer than N actionable opportunities/week net of fees, or any resolution-rule divergence observed.

---

### 4. On-chain metrics as regime filter on a swing trend system — MARGINAL, ~10–15%

**Edge hypothesis:** on-chain extremes (MVRV Z-score at historical tops/bottoms, exchange inflow spikes) mark regime boundaries that a price-based trend system would otherwise learn too late. Not a standalone signal — a filter that keeps the trend system out of (or sizes down in) statistically expensive regimes.

**Why it might survive:** it's an overlay, not a strategy — it only needs to add a few basis points of timing to a system whose economics already work (angle #1). Cheap to test: CoinMetrics Community API is free (no key, daily, history to 2010), DefiLlama free, mempool.space free.

**Documented evidence (thin):** University of Turin paper found MVRV Z-score / CVDD cycle-timing beat buy-and-hold with Monte Carlo significance — but cycle-timing on one asset's history means few trades and extreme data-mining risk; treat as suggestive. An MDPI volatility study found on-chain features "dominated by lagged volatility and trading volume" — secondary predictors. Exchange flows: sound logic (inflows = holders preparing to sell), visible in 2020–21, but contemporaneous not forecasting. **Standalone directional signals: DEAD** — Renault (2020, ~1M StockTwits messages): sentiment predicts BTC at ≤15-min but "impossible for a trader to make economic profits"; Johnson (2023): Fear & Greed "not useful for investment decisions"; fear/greed contrarian backtest: p=0.31, +15.9% vs +106.4% buy-and-hold. Funding rates as directional signal: DEAD (lagging, in every retail dashboard). Stablecoin supply claims: vendor marketing, not tested (2026 FinTech paper: depegs do not Granger-cause returns).

**Difficulty / capital / infrastructure:** Low technically (free daily data), high methodologically. The vendor problem is verified: Glassnode's relevant metrics sit behind $799/mo; the free metrics are exactly the widely-known ones — which is also why any edge in them is the most arbed.

**Probability assessment: ~10–15%**, and only as an overlay on angle #1, never standalone.

**What validation would look like:** point-in-time data only (replicate free-tier lag in backtests), hard train/test split (train ≤2021, test 2022+), deflated Sharpe / White's Reality Check across ALL variants tried, net of 100bps round-trip. Assume any signal on a public dashboard is priced in at the margin — demand forward OOS performance.

---

### 5. Favorite-longshot bias fade on Kalshi (buying expensive contracts) — MARGINAL, ~15%

**Edge hypothesis:** GWU 2026-001's finding in its simplest form: expensive (high-probability) contracts are systematically underpriced; cheap longshots overpriced. Buy 85–95¢ contracts, hold to settlement. Fees are cheapest exactly there (parabola: 0.63¢ at 90¢ vs 1.75¢ at 50¢).

**Why it might survive:** no speed needed, no prediction needed beyond the published bias, fee-optimal price region, hold-to-settlement simplicity.

**Documented evidence:** the GWU paper itself ("modestly positive" returns on expensive contracts). Counter: "modestly positive" pre-fee can be negative post-fee; the bias is now published and decaying; both makers AND takers earn negative returns on cheap contracts per the same paper.

**Probability assessment: ~15%.**

**What validation would look like:** paper-track a basket of 85¢+ contracts to settlement over 2–3 months, net of the real fee formula, vs a buy-and-hold-favorite benchmark. Kill criterion: net negative after 200+ contract resolutions.

---

## Declared dead (do not pursue without new evidence)

| Angle | Strongest reason |
|---|---|
| Crypto spot market making (retail tiers) | Maker *pays* 10bps on a 1-bp spread — negative before adverse selection; rebates need $20M/30d volume |
| Crypto perp market making (US retail) | Maker pays 2bps, no retail rebate; our own v3 (24% win rate) is the empirical confirmation |
| Cross-exchange spot arb on majors | <50ms latency requirement vs colocated HFT (82% vs 31% fill rates); break-even 0.3–0.5% on dislocations lasting seconds |
| Funding-rate / basis arb (retail) | Real edge, decaying ~11%/yr; $30 round-trip friction eats 10 days of income per $10K; at $500 ≈ $55/yr gross — not worth the monitoring |
| News-reaction trading on Kalshi (CPI/Fed) | NBER/Fed paper (Diercks, Katz & Wright 2026): Kalshi macro markets already match/beat Bloomberg consensus — racing Susquehanna's colocated infra for scraps |
| Cross-sectional crypto momentum | Han–Kang–Ryu: liquidated under realistic costs; structurally needs shorting US retail can't do |
| Sentiment/social directional trading | Renault: significant but "impossible to make economic profits"; Johnson: "not useful"; fear/greed backtest p=0.31 |
| Funding rates as directional signal | Lagging positioning readout, in every retail dashboard, arbed out |
| On-chain metrics as standalone signals | Best evidence is cycle-timing anecdote or lagging-flow description; nothing survives costs with significance |
| Long-lookback mean reversion on crypto | No fundamental anchor (no cash flows); equities evidence doesn't transfer |
| Deribit perp MM | −2.5bps rebate exists but venue is unavailable to US persons |

---

## Overall verdict

**No angle clears "viable."** The honest ranking:

1. **Long-only swing trend-following (~30%)** is the only angle with first-rate evidence, solved fee economics, and a mechanism that doesn't require speed or secrecy. Its enemies are time, variance, and psychology — not market structure.
2. Everything else is a **15–25% lottery ticket** (Kalshi tails, Kalshi–Polymarket arb, favorite-longshot fade) paying in unhedgeable risk (tail blowups, resolution mismatch) rather than in edge.
3. The retail fee/adverse-selection structure is the through-line: crypto spot kills you on fees; market making kills you on adverse selection; arb kills you on latency. Each territory's executioner is different, but there is always one.

**Recommended sequencing if proceeding:** build the long-only swing trend system on BTC/ETH daily data first (free data, fee-safe, best evidence, reuses the existing backtesting framework with walk-forward + deflated Sharpe). Only then test whether free on-chain metrics add anything as a regime filter. Do not build the alt-data system first — there is nothing under it. Run any prediction-market experiment only as a strictly-gated side validation (4–6 weeks paper, kill criteria in advance), never as the main bet.

**What this means for the original goal:** "prints money / financial freedom" is not on the table in any surveyed territory at retail scale. The closest thing to a real answer is also the most boring: a diversified trend system, run patiently for years, expected net Sharpe ~0.4, 15–25% drawdowns along the way. Anyone promising more is selling something.

---

## Key sources

- Moskowitz–Ooi–Pedersen (2012), time-series momentum; Hurst–Ooi–Pedersen (2017), "A Century of Evidence on Trend-Following Investing"
- Han–Kang–Ryu (SSRN 4675565), crypto momentum under realistic costs; Liu–Tsyvinski, crypto momentum
- Borri et al., funding/carry decay; He–Manela–Ross–von Wachter (arXiv 2212.06888), perp-spot deviations
- GWU 2026-001 (first systematic Kalshi study); Diercks–Katz–Wright (NBER 34702), Kalshi macro efficiency
- Della Vedova (2026, SSRN 6191618), "Who Profits from Prediction Markets"; Bartlett & O'Hara (2026, SSRN 6615739), Kalshi adverse selection; Gomez-Cram et al. (LBS/Yale 2026)
- Bloomberg/fa-mag.com on Polymarket P&L concentration (823 accounts >$100K; 0.1% captured 67%)
- Renault (2020), StockTwits sentiment; Johnson (2023), Fear & Greed; Turin on-chain cycles paper
- Kalshi fee schedule (effective July 7, 2026): taker `ceil(0.07 × P × (1−P))`, maker $0 standard / 0.0175 coefficient on sports series; Polymarket US: 0.30% taker / 0.20% maker rebate
- Practitioner repos: `50thycal/kalshi_bot` (measured adverse selection +1¢ → −8.6¢), `vinilpolepalli/quantfirm` (marked own metals desk PAPER/do-not-revive), `callancapitolo17/nflwork` (Kalshi EV/fee math), `artursepp/trendfollowingsystems`
- CoinLaw (prediction-market fee statistics 2026); defirate.com (live Kalshi spreads); Solidus Labs / WSJ (Polymarket P&L concentration)
