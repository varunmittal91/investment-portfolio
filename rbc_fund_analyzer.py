#!/usr/bin/env python3
"""
RBC Fund Analyzer - Fetches and analyzes RBC GAM mutual funds (Series F)
to recommend allocations for emergency and long-term savings.
"""

import argparse
import json
from datetime import datetime

from rbc_fund_data import get_funds, filter_series_f, safe_float


def score_emergency_fund(fund):
    """Score a fund for emergency allocation (0-100).
    Priorities: low risk, low MER, stable returns, liquidity."""
    score = 0

    risk_scores = {"Low": 40, "Low to Medium": 25, "Low-Medium": 25, "Medium": 5}
    score += risk_scores.get(fund["risk"], 0)

    mer = fund["mer"]
    if mer is not None:
        if mer <= 0.20:
            score += 25
        elif mer <= 0.40:
            score += 20
        elif mer <= 0.60:
            score += 15
        elif mer <= 0.80:
            score += 10
        elif mer <= 1.0:
            score += 5

    ac = fund["asset_class"].lower()
    name = fund["name"].lower()
    if "money market" in ac or "money market" in name:
        score += 20
    elif "bond" in ac or "fixed income" in ac or "bond" in name:
        score += 15
    elif "balanced" in ac:
        score += 5

    r1y = fund["1y"]
    if r1y is not None:
        if 2 <= r1y <= 8:
            score += 15
        elif 0 <= r1y < 2:
            score += 10
        elif 8 < r1y <= 12:
            score += 8
        elif r1y > 12:
            score += 3

    return score


def score_longterm_fund(fund):
    """Score a fund for long-term growth (0-100).
    Priorities: strong long-term returns, reasonable MER, acceptable risk."""
    score = 0

    r5y = fund["5y"]
    if r5y is not None:
        if r5y >= 12:
            score += 30
        elif r5y >= 9:
            score += 25
        elif r5y >= 7:
            score += 20
        elif r5y >= 5:
            score += 15
        elif r5y >= 3:
            score += 10

    r3y = fund["3y"]
    if r3y is not None:
        if r3y >= 12:
            score += 20
        elif r3y >= 9:
            score += 16
        elif r3y >= 7:
            score += 12
        elif r3y >= 5:
            score += 8

    mer = fund["mer"]
    if mer is not None:
        if mer <= 0.20:
            score += 20
        elif mer <= 0.40:
            score += 17
        elif mer <= 0.60:
            score += 14
        elif mer <= 0.80:
            score += 10
        elif mer <= 1.0:
            score += 6
        elif mer <= 1.5:
            score += 3

    risk_scores = {"Medium": 15, "Low to Medium": 12, "Low-Medium": 12,
                   "Medium to High": 10, "Medium-High": 10, "High": 5, "Low": 8}
    score += risk_scores.get(fund["risk"], 0)

    ac = fund["asset_class"].lower()
    if "balanced" in ac or "portfolio" in ac:
        score += 10
    elif "global" in ac or "international" in ac:
        score += 8
    elif "equity" in ac:
        score += 6

    dy = fund["div_yield"]
    if dy is not None and dy > 0.01:
        score += min(5, int(dy * 200))

    return score


def fmt(val):
    if val is None:
        return "-"
    return f"{val:.2f}"


def analyze(funds, savings_amount=None, emergency_pct=30):
    """Run full analysis and print recommendations."""
    f_funds = filter_series_f(funds)

    emergency_candidates = [f for f in f_funds if f["risk"] in ("Low", "Low to Medium", "Low-Medium")]
    for f in emergency_candidates:
        f["_emergency_score"] = score_emergency_fund(f)
    emergency_candidates.sort(key=lambda x: x["_emergency_score"], reverse=True)

    longterm_candidates = [f for f in f_funds if f["5y"] is not None]
    for f in longterm_candidates:
        f["_longterm_score"] = score_longterm_fund(f)
    longterm_candidates.sort(key=lambda x: x["_longterm_score"], reverse=True)

    print("=" * 90)
    print("RBC FUND ANALYSIS - SERIES F")
    print(f"Data as of: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"Total Series F funds analyzed: {len(f_funds)}")
    print("=" * 90)

    if savings_amount:
        emergency_amt = savings_amount * (emergency_pct / 100)
        longterm_amt = savings_amount - emergency_amt
        print(f"\nSavings: ${savings_amount:,.2f}")
        print(f"  Emergency fund ({emergency_pct}%): ${emergency_amt:,.2f}")
        print(f"  Long-term growth ({100 - emergency_pct}%): ${longterm_amt:,.2f}")

    print("\n" + "=" * 90)
    print("EMERGENCY FUND PICKS (Low Risk, Low Cost, Stable)")
    print("-" * 90)
    print(f"{'Rank':<5} {'Score':<6} {'Code':<10} {'Fund Name':<42} {'Risk':<12} {'MER%':<7} {'1Y%':<8} {'3Y%':<8}")
    print("-" * 90)
    for i, f in enumerate(emergency_candidates[:15], 1):
        print(f"{i:<5} {f['_emergency_score']:<6} {f['code']:<10} {f['name'][:41]:<42} {f['risk']:<12} {fmt(f['mer']):<7} {fmt(f['1y']):<8} {fmt(f['3y']):<8}")

    print("\n" + "=" * 90)
    print("LONG-TERM GROWTH PICKS (Strong Returns, Reasonable Cost)")
    print("-" * 90)
    print(f"{'Rank':<5} {'Score':<6} {'Code':<10} {'Fund Name':<42} {'Risk':<12} {'MER%':<7} {'3Y%':<8} {'5Y%':<8} {'10Y%':<8}")
    print("-" * 90)
    for i, f in enumerate(longterm_candidates[:15], 1):
        print(f"{i:<5} {f['_longterm_score']:<6} {f['code']:<10} {f['name'][:41]:<42} {f['risk']:<12} {fmt(f['mer']):<7} {fmt(f['3y']):<8} {fmt(f['5y']):<8} {fmt(f['10y']):<8}")

    print("\n" + "=" * 90)
    print("BEST LOW-COST INDEX FUNDS (MER < 0.30%)")
    print("-" * 90)
    low_cost = sorted([f for f in f_funds if f["mer"] is not None and f["mer"] < 0.30], key=lambda x: x["mer"])
    print(f"{'Code':<10} {'Fund Name':<48} {'MER%':<7} {'Risk':<12} {'1Y%':<8} {'5Y%':<8}")
    print("-" * 90)
    for f in low_cost[:10]:
        print(f"{f['code']:<10} {f['name'][:47]:<48} {fmt(f['mer']):<7} {f['risk']:<12} {fmt(f['1y']):<8} {fmt(f['5y']):<8}")

    print("\n" + "=" * 90)
    print("BALANCED ALL-IN-ONE OPTIONS (Simplest for Small Savings)")
    print("-" * 90)
    balanced = [f for f in f_funds if "balanced" in f["asset_class"].lower() or "portfolio" in f["name"].lower()]
    for f in balanced:
        f["_longterm_score"] = score_longterm_fund(f)
    balanced.sort(key=lambda x: x["_longterm_score"], reverse=True)
    print(f"{'Code':<10} {'Fund Name':<48} {'Risk':<12} {'MER%':<7} {'1Y%':<8} {'5Y%':<8}")
    print("-" * 90)
    for f in balanced[:10]:
        print(f"{f['code']:<10} {f['name'][:47]:<48} {f['risk']:<12} {fmt(f['mer']):<7} {fmt(f['1y']):<8} {fmt(f['5y']):<8}")

    print("\n" + "=" * 90)
    print("SUGGESTED PORTFOLIO STRATEGY")
    print("=" * 90)
    top_emergency = emergency_candidates[:3]
    top_growth = longterm_candidates[:3]
    print("\nEMERGENCY BUCKET (suggest 3-6 months of expenses):")
    for i, f in enumerate(top_emergency, 1):
        print(f"  {i}. {f['name']} ({f['code']}) - MER: {fmt(f['mer'])}%, Risk: {f['risk']}")
    print("\nLONG-TERM BUCKET (remaining savings, 5+ year horizon):")
    for i, f in enumerate(top_growth, 1):
        print(f"  {i}. {f['name']} ({f['code']}) - MER: {fmt(f['mer'])}%, 5Y: {fmt(f['5y'])}%")

    if savings_amount and savings_amount < 5000:
        print("\nNOTE FOR SMALL SAVINGS:")
        print("  - Consider a single balanced/all-in-one fund to keep things simple")
        print("  - Keep emergency money in a HISA first")
        print("  - Start investing once you have 3+ months expenses saved")


def dump_json(funds):
    f_funds = filter_series_f(funds)
    for f in f_funds:
        f["_emergency_score"] = score_emergency_fund(f)
        f["_longterm_score"] = score_longterm_fund(f)
    print(json.dumps(f_funds, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="RBC Fund Analyzer")
    parser.add_argument("--savings", type=float, help="Total savings amount in CAD")
    parser.add_argument("--emergency-pct", type=int, default=30, help="Percentage for emergency fund (default: 30)")
    parser.add_argument("--json", action="store_true", help="Output all scored funds as JSON")
    parser.add_argument("--max-mer", type=float, help="Filter funds with MER below this threshold")
    parser.add_argument("--risk", choices=["Low", "Low-Medium", "Medium", "Medium-High", "High"], help="Filter by risk level")
    parser.add_argument("--cached", action="store_true", help="Use cached data from rbcgam_fds_fund_data.json")
    args = parser.parse_args()

    funds = get_funds(cached=args.cached)

    if args.max_mer:
        funds = [f for f in funds if f["mer"] is not None and f["mer"] <= args.max_mer]
    if args.risk:
        funds = [f for f in funds if f["risk"] == args.risk]

    if args.json:
        dump_json(funds)
    else:
        analyze(funds, savings_amount=args.savings, emergency_pct=args.emergency_pct)


if __name__ == "__main__":
    main()
