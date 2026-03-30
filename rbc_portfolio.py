#!/usr/bin/env python3
"""
RBC Portfolio Manager - Config-driven portfolio tool for DCA investing
across TFSA, RRSP, and non-registered accounts with RBC GAM Series F funds.

Usage:
    python3 rbc_portfolio.py buy              # Monthly buy orders
    python3 rbc_portfolio.py status           # Portfolio overview
    python3 rbc_portfolio.py rebalance        # Rebalancing recommendations
    python3 rbc_portfolio.py validate         # Check config for errors
    python3 rbc_portfolio.py project          # 12-month projection
    python3 rbc_portfolio.py init             # Print starter config
"""

import argparse
import json
import sys
from datetime import datetime, date

from rbc_fund_data import get_funds, filter_series_f, build_fund_lookup, safe_float

# ─── Config ──────────────────────────────────────────────────────────────────

def load_config(path="portfolio_config.json"):
    with open(path) as f:
        return json.load(f)


def validate_config(config, fund_lookup):
    """Return (errors, warnings) lists."""
    errors, warnings = [], []

    for acct_key, acct in config["accounts"].items():
        alloc = acct.get("target_allocation", {})
        total_pct = sum(a["pct"] for a in alloc.values())
        if abs(total_pct - 100) > 0.01:
            errors.append(f"{acct['label']}: allocation sums to {total_pct:.1f}%, not 100%")

        for code in alloc:
            if code not in fund_lookup:
                errors.append(f"{acct['label']}: fund {code} not found in RBC Series F data")

        monthly = acct.get("monthly_contribution", 0)
        room = acct.get("contribution_room")
        if room is not None and monthly * 12 > room:
            warnings.append(f"{acct['label']}: annual contributions ${monthly*12:,.0f} exceed room ${room:,.0f}")

        for code, val in acct.get("holdings", {}).items():
            if code not in fund_lookup:
                warnings.append(f"{acct['label']}: holding {code} not in fund data")

    total_monthly = sum(a.get("monthly_contribution", 0) for a in config["accounts"].values())
    cfg_monthly = config["profile"].get("monthly_contribution", 0)
    if cfg_monthly > 0 and abs(total_monthly - cfg_monthly) > 1:
        warnings.append(f"Account contributions total ${total_monthly:,.0f}/mo but profile says ${cfg_monthly:,.0f}/mo")

    return errors, warnings


# ─── Tax Optimization ────────────────────────────────────────────────────────

TAX_TIPS = {
    # (region, tax_treatment) -> suggestion
    ("unitedstates", "tax_free"): "US equities in TFSA lose 15% withholding tax on dividends. Better in RRSP (treaty exemption).",
    ("unitedstates", "taxable"): "US equities in non-registered lose 15% withholding tax. Consider RRSP.",
}


def check_tax_optimization(config, fund_lookup):
    """Return list of tax optimization suggestions."""
    suggestions = []
    for acct_key, acct in config["accounts"].items():
        tax = acct.get("tax_treatment", "")
        for code in acct.get("target_allocation", {}):
            fund = fund_lookup.get(code, {})
            region = fund.get("region", "")
            name = fund.get("name", "")
            ac = fund.get("asset_class", "").lower()
            dy = fund.get("div_yield") or 0

            tip = TAX_TIPS.get((region, tax))
            if tip:
                suggestions.append(f"  {acct['label']}/{code} ({name[:35]}): {tip}")

            # Canadian dividends wasted in RRSP
            if "canadian" in ac and dy > 0.015 and tax == "tax_deferred":
                suggestions.append(
                    f"  {acct['label']}/{code} ({name[:35]}): "
                    f"Canadian dividends get tax credit in non-reg, wasted in RRSP.")

            # Growth funds in taxable
            if tax == "taxable" and ("growth" in name.lower() or "index" in name.lower()):
                if "money market" not in name.lower() and "bond" not in name.lower():
                    suggestions.append(
                        f"  {acct['label']}/{code} ({name[:35]}): "
                        f"Growth/index funds are more tax-efficient in TFSA (tax-free cap gains).")

    return suggestions


# ─── Portfolio Calculations ──────────────────────────────────────────────────

def compute_account_state(acct, fund_lookup):
    """Compute current allocation vs target for one account."""
    holdings = acct.get("holdings", {})
    total = sum(holdings.values())
    alloc = acct.get("target_allocation", {})

    rows = []
    for code, info in alloc.items():
        current_val = holdings.get(code, 0)
        current_pct = (current_val / total * 100) if total > 0 else 0
        target_pct = info["pct"]
        drift = current_pct - target_pct
        fund = fund_lookup.get(code, {})
        rows.append({
            "code": code,
            "label": info.get("label", fund.get("name", code)),
            "target_pct": target_pct,
            "current_val": current_val,
            "current_pct": current_pct,
            "drift": drift,
            "fund": fund,
        })
    return rows, total


def generate_buy_orders(config, fund_lookup):
    """Generate this month's buy orders across all accounts."""
    orders = []
    for acct_key, acct in sorted(config["accounts"].items(), key=lambda x: x[1].get("priority", 99)):
        contribution = acct.get("monthly_contribution", 0)
        if contribution <= 0:
            continue

        holdings = acct.get("holdings", {})
        total_after = sum(holdings.values()) + contribution
        alloc = acct.get("target_allocation", {})

        # Compute gap for each fund
        buys = []
        for code, info in alloc.items():
            target_val = total_after * (info["pct"] / 100)
            current_val = holdings.get(code, 0)
            gap = max(0, target_val - current_val)
            fund = fund_lookup.get(code, {})
            buys.append({
                "code": code,
                "label": info.get("label", fund.get("name", code)),
                "gap": gap,
                "target_pct": info["pct"],
            })

        # Sort by largest gap, allocate contribution
        buys.sort(key=lambda x: x["gap"], reverse=True)
        remaining = contribution
        account_orders = []
        for b in buys:
            if remaining <= 0:
                break
            buy_amt = min(b["gap"], remaining)
            if buy_amt >= 50:  # min practical purchase
                account_orders.append({
                    "account": acct["label"],
                    "account_key": acct_key,
                    "code": b["code"],
                    "label": b["label"],
                    "amount": round(buy_amt, 2),
                    "target_pct": b["target_pct"],
                })
                remaining -= buy_amt

        # Distribute any rounding residual to the largest allocation
        if remaining >= 1 and account_orders:
            account_orders[0]["amount"] = round(account_orders[0]["amount"] + remaining, 2)

        orders.extend(account_orders)

    return orders


def generate_rebalance_orders(config, fund_lookup):
    """Generate buy-only rebalancing recommendations for drifted positions."""
    band = config["profile"].get("rebalance_band_pct", 5)
    recs = []
    for acct_key, acct in config["accounts"].items():
        rows, total = compute_account_state(acct, fund_lookup)
        if total == 0:
            continue
        for r in rows:
            if r["drift"] < -band:  # underweight beyond band
                target_val = total * (r["target_pct"] / 100)
                buy_amt = target_val - r["current_val"]
                recs.append({
                    "account": acct["label"],
                    "code": r["code"],
                    "label": r["label"],
                    "drift": r["drift"],
                    "buy_to_fix": round(buy_amt, 2),
                })
    return recs


# ─── Projection ──────────────────────────────────────────────────────────────

def project_portfolio(config, fund_lookup, months=12):
    """Project portfolio growth over N months using fund's historical returns."""
    projections = []

    for month in range(1, months + 1):
        month_total = 0
        account_details = {}

        for acct_key, acct in config["accounts"].items():
            monthly = acct.get("monthly_contribution", 0)
            alloc = acct.get("target_allocation", {})
            holdings = acct.get("holdings", {})
            acct_total = sum(holdings.values())

            details = []
            for code, info in alloc.items():
                fund = fund_lookup.get(code, {})
                # Use 5-year return as baseline, fallback to 3-year, then 1-year
                annual_return = fund.get("5y") or fund.get("3y") or fund.get("1y") or 0
                monthly_return = (1 + annual_return / 100) ** (1/12) - 1

                existing = holdings.get(code, 0)
                # Grow existing holdings
                grown = existing * (1 + monthly_return) ** month
                # Sum of DCA contributions grown for remaining months
                monthly_buy = monthly * (info["pct"] / 100)
                dca_value = sum(monthly_buy * (1 + monthly_return) ** (month - m) for m in range(1, month + 1))
                total_val = grown + dca_value

                details.append({
                    "code": code,
                    "label": info["label"],
                    "value": round(total_val, 2),
                    "contributed": round(monthly_buy * month + existing, 2),
                    "return_rate": annual_return,
                })

            acct_value = sum(d["value"] for d in details)
            acct_contributed = sum(d["contributed"] for d in details)
            account_details[acct_key] = {
                "label": acct["label"],
                "value": round(acct_value, 2),
                "contributed": round(acct_contributed, 2),
                "gain": round(acct_value - acct_contributed, 2),
                "details": details,
            }
            month_total += acct_value

        total_contributed = sum(v["contributed"] for v in account_details.values())
        projections.append({
            "month": month,
            "total_value": round(month_total, 2),
            "total_contributed": round(total_contributed, 2),
            "total_gain": round(month_total - total_contributed, 2),
            "accounts": account_details,
        })

    return projections


# ─── Output Formatting ───────────────────────────────────────────────────────

def fmt(val, prefix="$"):
    if val is None:
        return "-"
    if prefix == "$":
        return f"${val:,.2f}"
    return f"{val:.2f}%"


def print_buy_report(config, fund_lookup):
    orders = generate_buy_orders(config, fund_lookup)
    total_monthly = sum(o["amount"] for o in orders)
    profile = config["profile"]

    print("=" * 85)
    print("RBC PORTFOLIO MANAGER — MONTHLY BUY ORDERS")
    print(f"Date: {date.today()} | Plan: ${profile['annual_investment']:,.0f}/year over 12 months")
    print("=" * 85)

    print(f"\n  Monthly budget:  ${profile['monthly_contribution']:,.0f}")
    print(f"  This month buys: ${total_monthly:,.2f}")
    remaining_months = config["dca_schedule"].get("months_remaining", 12)
    print(f"  Months remaining: {remaining_months}")

    # Group orders by account
    current_acct = None
    step = 1
    action_steps = []

    for o in orders:
        if o["account"] != current_acct:
            current_acct = o["account"]
            acct = config["accounts"][o["account_key"]]
            room = acct.get("contribution_room")
            room_str = f" | Room: ${room:,.0f}" if room else ""
            print(f"\n  {'─' * 80}")
            print(f"  ACCOUNT: {current_acct}{room_str}")
            print(f"  {'─' * 80}")
            print(f"  {'Code':<10} {'Fund':<42} {'Target':<8} {'BUY':>10}")
            print(f"  {'─' * 80}")

        fund = fund_lookup.get(o["code"], {})
        r5y = fund.get("5y")
        print(f"  {o['code']:<10} {o['label'][:41]:<42} {o['target_pct']:>5.0f}%  {fmt(o['amount']):>10}")
        action_steps.append(f"  {step}. Buy {fmt(o['amount'])} of {o['code']} in {o['account']}")
        step += 1

    # Tax notes
    tax_tips = check_tax_optimization(config, fund_lookup)
    if tax_tips:
        print(f"\n  {'─' * 80}")
        print("  TAX OPTIMIZATION NOTES")
        print(f"  {'─' * 80}")
        for tip in tax_tips:
            print(f"  {tip}")

    # Action checklist
    print(f"\n  {'─' * 80}")
    print("  ACTION CHECKLIST")
    print(f"  {'─' * 80}")
    for s in action_steps:
        print(s)
    print(f"\n  After purchasing, update holdings in portfolio_config.json")

    print()


def print_status(config, fund_lookup):
    print("=" * 95)
    print("RBC PORTFOLIO — CURRENT STATUS")
    print(f"Date: {date.today()}")
    print("=" * 95)

    grand_total = 0
    grand_contributed = 0

    for acct_key, acct in sorted(config["accounts"].items(), key=lambda x: x[1].get("priority", 99)):
        rows, total = compute_account_state(acct, fund_lookup)
        grand_total += total
        room = acct.get("contribution_room")
        room_str = f" | Room: ${room:,.0f}" if room else ""

        print(f"\n  ACCOUNT: {acct['label']}{room_str} | Balance: {fmt(total)}")
        print(f"  {'─' * 90}")

        if total == 0:
            print(f"  No holdings yet. Monthly contribution: {fmt(acct.get('monthly_contribution', 0))}")
            print(f"  {'Code':<10} {'Fund':<40} {'Target':>8}")
            print(f"  {'─' * 90}")
            for code, info in acct.get("target_allocation", {}).items():
                fund = fund_lookup.get(code, {})
                r5y = fund.get("5y")
                r_str = f"  5Y: {r5y:.1f}%" if r5y else ""
                print(f"  {code:<10} {info['label'][:39]:<40} {info['pct']:>6.0f}%{r_str}")
        else:
            band = config["profile"].get("rebalance_band_pct", 5)
            print(f"  {'Code':<10} {'Fund':<35} {'Target':>8} {'Current':>8} {'Value':>10} {'Drift':>8} {'Status':<12}")
            print(f"  {'─' * 90}")
            for r in rows:
                drift_str = f"{r['drift']:+.1f}%"
                if abs(r["drift"]) > band:
                    status = "REBALANCE"
                elif abs(r["drift"]) > band / 2:
                    status = "WATCH"
                else:
                    status = "OK"
                print(f"  {r['code']:<10} {r['label'][:34]:<35} {r['target_pct']:>6.0f}%  {r['current_pct']:>6.1f}%  {fmt(r['current_val']):>10} {drift_str:>8}  {status:<12}")

    print(f"\n  {'═' * 90}")
    print(f"  TOTAL PORTFOLIO VALUE: {fmt(grand_total)}")
    print(f"  {'═' * 90}")


def print_projection(config, fund_lookup):
    projections = project_portfolio(config, fund_lookup, months=12)

    print("=" * 95)
    print("RBC PORTFOLIO — 12-MONTH PROJECTION")
    print(f"Based on historical 5-year annualized returns (not guaranteed)")
    print("=" * 95)

    # Summary table
    print(f"\n  {'Month':<8} {'Contributed':>14} {'Projected Value':>16} {'Est. Gain':>14} {'Gain %':>8}")
    print(f"  {'─' * 62}")

    milestones = [1, 2, 3, 6, 9, 12]
    for p in projections:
        if p["month"] in milestones:
            gain_pct = (p["total_gain"] / p["total_contributed"] * 100) if p["total_contributed"] > 0 else 0
            print(f"  {p['month']:<8} {fmt(p['total_contributed']):>14} {fmt(p['total_value']):>16} {fmt(p['total_gain']):>14} {gain_pct:>7.1f}%")

    # End-of-year breakdown by account
    final = projections[-1]
    print(f"\n  {'─' * 90}")
    print(f"  END OF YEAR BREAKDOWN (Month 12)")
    print(f"  {'─' * 90}")
    print(f"  {'Account':<18} {'Contributed':>14} {'Projected':>14} {'Gain':>12} {'Gain %':>8}")
    print(f"  {'─' * 90}")

    for acct_key, ad in final["accounts"].items():
        gain_pct = (ad["gain"] / ad["contributed"] * 100) if ad["contributed"] > 0 else 0
        print(f"  {ad['label']:<18} {fmt(ad['contributed']):>14} {fmt(ad['value']):>14} {fmt(ad['gain']):>12} {gain_pct:>7.1f}%")

    print(f"  {'─' * 90}")
    total_gain_pct = (final["total_gain"] / final["total_contributed"] * 100) if final["total_contributed"] > 0 else 0
    print(f"  {'TOTAL':<18} {fmt(final['total_contributed']):>14} {fmt(final['total_value']):>14} {fmt(final['total_gain']):>12} {total_gain_pct:>7.1f}%")

    # Per-fund detail
    print(f"\n  {'─' * 90}")
    print(f"  FUND DETAIL (End of Year)")
    print(f"  {'─' * 90}")
    print(f"  {'Account':<12} {'Code':<10} {'Fund':<30} {'Contributed':>12} {'Projected':>12} {'Rate':>7}")
    print(f"  {'─' * 90}")

    for acct_key, ad in final["accounts"].items():
        for d in ad["details"]:
            gain = d["value"] - d["contributed"]
            print(f"  {ad['label']:<12} {d['code']:<10} {d['label'][:29]:<30} {fmt(d['contributed']):>12} {fmt(d['value']):>12} {d['return_rate']:>5.1f}%")

    # Conservative scenario
    print(f"\n  {'─' * 90}")
    print(f"  CONSERVATIVE SCENARIO (half of historical returns)")
    print(f"  {'─' * 90}")
    conservative = project_portfolio_scaled(config, fund_lookup, months=12, scale=0.5)
    cf = conservative[-1]
    c_gain_pct = (cf["total_gain"] / cf["total_contributed"] * 100) if cf["total_contributed"] > 0 else 0
    print(f"  Contributed: {fmt(cf['total_contributed'])}  |  Projected: {fmt(cf['total_value'])}  |  Gain: {fmt(cf['total_gain'])} ({c_gain_pct:.1f}%)")

    # Bear scenario
    bear = project_portfolio_scaled(config, fund_lookup, months=12, scale=-0.15)
    bf = bear[-1]
    b_gain_pct = (bf["total_gain"] / bf["total_contributed"] * 100) if bf["total_contributed"] > 0 else 0
    print(f"\n  BEAR MARKET SCENARIO (15% annual decline)")
    print(f"  Contributed: {fmt(bf['total_contributed'])}  |  Projected: {fmt(bf['total_value'])}  |  Loss: {fmt(bf['total_gain'])} ({b_gain_pct:.1f}%)")

    print(f"\n  * Past performance does not guarantee future results.")
    print(f"  * Actual returns will differ. Markets can drop significantly in any year.")
    print()


def project_portfolio_scaled(config, fund_lookup, months=12, scale=1.0):
    """Like project_portfolio but scales the return rate."""
    projections = []
    for month in range(1, months + 1):
        month_total = 0
        account_details = {}
        for acct_key, acct in config["accounts"].items():
            monthly = acct.get("monthly_contribution", 0)
            alloc = acct.get("target_allocation", {})
            holdings = acct.get("holdings", {})

            details = []
            for code, info in alloc.items():
                fund = fund_lookup.get(code, {})
                annual_return = fund.get("5y") or fund.get("3y") or fund.get("1y") or 0
                if scale < 0:
                    annual_return = scale * 100  # override to flat rate
                else:
                    annual_return = annual_return * scale
                monthly_return = (1 + annual_return / 100) ** (1/12) - 1

                existing = holdings.get(code, 0)
                grown = existing * (1 + monthly_return) ** month
                monthly_buy = monthly * (info["pct"] / 100)
                dca_value = sum(monthly_buy * (1 + monthly_return) ** (month - m) for m in range(1, month + 1))
                total_val = grown + dca_value

                details.append({
                    "code": code, "label": info["label"],
                    "value": round(total_val, 2),
                    "contributed": round(monthly_buy * month + existing, 2),
                    "return_rate": annual_return,
                })

            acct_value = sum(d["value"] for d in details)
            acct_contributed = sum(d["contributed"] for d in details)
            account_details[acct_key] = {
                "label": acct["label"],
                "value": round(acct_value, 2),
                "contributed": round(acct_contributed, 2),
                "gain": round(acct_value - acct_contributed, 2),
                "details": details,
            }
            month_total += acct_value
        total_contributed = sum(v["contributed"] for v in account_details.values())
        projections.append({
            "month": month,
            "total_value": round(month_total, 2),
            "total_contributed": round(total_contributed, 2),
            "total_gain": round(month_total - total_contributed, 2),
            "accounts": account_details,
        })
    return projections


def print_rebalance(config, fund_lookup):
    recs = generate_rebalance_orders(config, fund_lookup)
    band = config["profile"].get("rebalance_band_pct", 5)

    print("=" * 85)
    print(f"RBC PORTFOLIO — REBALANCING (band: +/-{band}%)")
    print("=" * 85)

    if not recs:
        print("\n  All positions within rebalancing bands. No action needed.")
    else:
        print(f"\n  {'Account':<18} {'Code':<10} {'Fund':<35} {'Drift':>8} {'Buy to Fix':>12}")
        print(f"  {'─' * 85}")
        for r in recs:
            print(f"  {r['account']:<18} {r['code']:<10} {r['label'][:34]:<35} {r['drift']:>+6.1f}%  {fmt(r['buy_to_fix']):>12}")
    print()


def print_validate(config, fund_lookup):
    errors, warnings = validate_config(config, fund_lookup)

    print("=" * 70)
    print("RBC PORTFOLIO — CONFIG VALIDATION")
    print("=" * 70)

    if not errors and not warnings:
        print("\n  Config is valid. No issues found.")
    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    [X] {e}")
    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"    [!] {w}")

    # Also show allocation summary
    print(f"\n  ALLOCATION SUMMARY:")
    total_monthly = 0
    for acct_key, acct in config["accounts"].items():
        m = acct.get("monthly_contribution", 0)
        total_monthly += m
        print(f"    {acct['label']}: ${m:,.0f}/mo")
        for code, info in acct.get("target_allocation", {}).items():
            fund = fund_lookup.get(code, {})
            mer = fund.get("mer")
            risk = fund.get("risk", "?")
            mer_str = f"MER {mer:.2f}%" if mer else "MER ?"
            print(f"      {code} {info['label'][:35]:<36} {info['pct']:>3}%  {mer_str}  Risk: {risk}")
    print(f"    {'─' * 40}")
    print(f"    Total: ${total_monthly:,.0f}/mo  (${total_monthly*12:,.0f}/yr)")

    # Tax check
    tips = check_tax_optimization(config, fund_lookup)
    if tips:
        print(f"\n  TAX OPTIMIZATION TIPS:")
        for t in tips:
            print(f"  {t}")

    print()


def print_init():
    """Print a starter portfolio_config.json."""
    starter = {
        "profile": {
            "name": "Your Name",
            "annual_investment": 24000,
            "monthly_contribution": 2000,
            "start_date": datetime.now().strftime("%Y-%m"),
            "risk_tolerance": "medium",
            "investment_horizon_years": 10,
            "rebalance_band_pct": 5
        },
        "accounts": {
            "tfsa": {
                "label": "TFSA",
                "contribution_room": 7000,
                "current_balance": 0,
                "monthly_contribution": 900,
                "priority": 1,
                "tax_treatment": "tax_free",
                "holdings": {},
                "target_allocation": {
                    "RBF660": {"pct": 50, "label": "RBC Select Aggressive Growth Portfolio"},
                    "RBF5733": {"pct": 30, "label": "RBC Canadian Index Fund"},
                    "RBF5737": {"pct": 20, "label": "RBC U.S. Index Fund"}
                }
            },
            "rrsp": {
                "label": "RRSP",
                "contribution_room": 12000,
                "current_balance": 0,
                "monthly_contribution": 700,
                "priority": 2,
                "tax_treatment": "tax_deferred",
                "holdings": {},
                "target_allocation": {
                    "RBF2143": {"pct": 40, "label": "RBC U.S. Equity Index ETF Fund"},
                    "RBF5736": {"pct": 30, "label": "RBC Intl Equity Currency Neutral Index ETF"},
                    "RBF900": {"pct": 30, "label": "RBC Canadian Bond Index ETF Fund"}
                }
            },
            "non_registered": {
                "label": "Non-Registered",
                "current_balance": 0,
                "monthly_contribution": 400,
                "priority": 3,
                "tax_treatment": "taxable",
                "holdings": {},
                "target_allocation": {
                    "RBF607": {"pct": 60, "label": "RBC Canadian Dividend Fund"},
                    "RBF636": {"pct": 40, "label": "RBC Canadian Money Market Fund"}
                }
            }
        },
        "dca_schedule": {
            "frequency": "monthly",
            "day_of_month": 1,
            "months_remaining": 12
        }
    }
    print(json.dumps(starter, indent=2))


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="RBC Portfolio Manager — Config-driven DCA investing tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Commands:
  buy        Show this month's buy orders
  status     Portfolio overview with drift analysis
  rebalance  Rebalancing recommendations
  project    12-month growth projection
  validate   Check config for errors
  init       Print a starter portfolio_config.json""")

    parser.add_argument("command", choices=["buy", "status", "rebalance", "project", "validate", "init"])
    parser.add_argument("--config", default="portfolio_config.json", help="Config file path")
    parser.add_argument("--cached", action="store_true", help="Use cached fund data")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.command == "init":
        print_init()
        return

    config = load_config(args.config)
    funds = get_funds(cached=args.cached)
    f_funds = filter_series_f(funds)
    fund_lookup = build_fund_lookup(f_funds)

    if args.command == "validate":
        print_validate(config, fund_lookup)
    elif args.command == "buy":
        print_buy_report(config, fund_lookup)
    elif args.command == "status":
        print_status(config, fund_lookup)
    elif args.command == "rebalance":
        print_rebalance(config, fund_lookup)
    elif args.command == "project":
        if args.json:
            projections = project_portfolio(config, fund_lookup, months=12)
            print(json.dumps(projections, indent=2))
        else:
            print_projection(config, fund_lookup)


if __name__ == "__main__":
    main()
