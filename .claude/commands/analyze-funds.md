---
description: Analyze RBC mutual funds and recommend picks for emergency savings and long-term investment
allowed-tools: Bash, Read, WebFetch, Write, Edit
---

# RBC Fund Analyzer

Analyze RBC GAM Series F mutual funds to find the best picks.

## Commands

```bash
cd /Users/vmittal/Code/personal/stocks

# Full analysis with savings amount
python3 rbc_fund_analyzer.py --savings 5000

# Use cached data (faster)
python3 rbc_fund_analyzer.py --cached --savings 5000

# Filter by MER or risk
python3 rbc_fund_analyzer.py --cached --max-mer 0.5
python3 rbc_fund_analyzer.py --cached --risk Low

# JSON output for custom analysis
python3 rbc_fund_analyzer.py --cached --json
```

## What It Does

Scores 279 Series F funds on two dimensions:
1. **Emergency Fund Score** — low risk, low MER, stable returns, money market/bond preference
2. **Long-Term Growth Score** — strong 5Y/3Y returns, low MER, medium risk, diversification

## For Portfolio Management

Use the `/project:portfolio` command instead, which provides:
- Monthly buy orders across TFSA/RRSP/non-registered accounts
- 12-month projections with bull/bear/conservative scenarios
- Rebalancing alerts when drift exceeds 5%
- Tax optimization tips

## Disclaimer
Not financial advice. Past performance doesn't guarantee future results. Consult a licensed advisor.
