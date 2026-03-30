---
description: Manage RBC mutual fund portfolio — buy orders, projections, rebalancing, and status
allowed-tools: Bash, Read, Write, Edit
---

# RBC Portfolio Manager

You are helping manage a DCA (dollar-cost averaging) investment portfolio across TFSA, RRSP, and non-registered accounts using RBC GAM Series F funds.

## Available Commands

Run from `/Users/vmittal/Code/personal/stocks/`:

```bash
# Monthly buy orders — what to purchase this month
python3 rbc_portfolio.py buy --cached

# Portfolio status — current holdings vs targets
python3 rbc_portfolio.py status --cached

# 12-month projection — expected growth scenarios
python3 rbc_portfolio.py project --cached

# Rebalancing check — drift beyond 5% band
python3 rbc_portfolio.py rebalance --cached

# Validate config — check for errors
python3 rbc_portfolio.py validate --cached

# Fresh data (live API fetch instead of cache)
python3 rbc_portfolio.py buy
```

## Monthly Workflow

Each month the user should:
1. Run `buy` to see what to purchase
2. Execute the buys in their RBC accounts
3. Update `portfolio_config.json` holdings with new balances
4. Run `status` to confirm allocations look right
5. Run `rebalance` if they suspect drift

## Config File

The portfolio is defined in `portfolio_config.json`. Key sections:
- `profile` — annual budget, risk tolerance, monthly contribution
- `accounts` — TFSA/RRSP/non-reg with target allocations and current holdings
- `holdings` — update these with dollar values after each purchase

## When to Refresh Cache

Run without `--cached` to get fresh fund data when:
- Checking current prices before buying
- Monthly at the start of a new contribution cycle
- When fund performance data needs updating

## Tax Optimization Rules
- **RRSP**: Best for US equities (avoids 15% withholding tax), bonds (shelters interest income)
- **TFSA**: Best for high-growth/index funds (tax-free capital gains)
- **Non-registered**: Best for Canadian dividend funds (dividend tax credit)

## Disclaimers
Always remind the user: this is not financial advice, past performance doesn't guarantee future results, and they should consult a licensed advisor.
