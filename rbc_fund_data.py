#!/usr/bin/env python3
"""
Shared RBC GAM fund data loading module.
Used by rbc_fund_analyzer.py and rbc_portfolio.py.
"""

import json
import sys
from urllib.request import urlopen, Request

FDS_URL = "https://www.rbcgam.com/api/vtl/fds-fund-list?series=f&tab=overview&language_id=1"
DOTCMS_URL = "https://www.rbcgam.com/api/vtl/dotcms-fund-list?series=f&language_id=1"


def safe_float(val):
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def fetch_json(url):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    if isinstance(data, dict) and "fundData" in data:
        return data["fundData"]
    return data


def _normalize_fund(fds_record, dotcms_record=None):
    """Convert raw API records into a normalized fund dict."""
    f = fds_record
    dm = dotcms_record or {}
    code = f.get("rbcFundCode", "")
    perf = f.get("performance", {}) or {}
    chars = f.get("characteristics", {}) or {}

    return {
        "code": code,
        "series": f.get("series", ""),
        "name": (f.get("fundName", {}).get("en") or "").strip(),
        "asset_class": (f.get("assetClass", {}).get("en") or "").strip(),
        "category": dm.get("category", ""),
        "region": dm.get("region", ""),
        "currency": dm.get("currency", ""),
        "risk": (f.get("risk", {}).get("en") or "").strip(),
        "mgmt_fee": safe_float(f.get("managementFees")),
        "mer": safe_float(f.get("mer")),
        "price": safe_float(f.get("price")),
        "div_yield": safe_float(chars.get("dividendYield")),
        "ytd": safe_float(perf.get("ytd")),
        "1m": safe_float(perf.get("1Mth")),
        "3m": safe_float(perf.get("3Mth")),
        "6m": safe_float(perf.get("6Mth")),
        "1y": safe_float(perf.get("1Yr")),
        "3y": safe_float(perf.get("3Yr")),
        "5y": safe_float(perf.get("5Yr")),
        "10y": safe_float(perf.get("10Yr")),
        "since_inception": safe_float(perf.get("sinceInception")),
        "inception_date": f.get("inceptionDate", ""),
    }


def _build_dotcms_map(dotcms_list):
    """Index DotCMS records by fund code (handles both key names)."""
    m = {}
    for d in dotcms_list:
        key = d.get("fundCode", d.get("rbcFundCode", ""))
        if key:
            m[key] = d
    return m


def _merge_funds(fds_list, dotcms_list):
    dotcms_map = _build_dotcms_map(dotcms_list)
    funds = []
    for f in fds_list:
        code = f.get("rbcFundCode", "")
        dm = dotcms_map.get(code, {})
        funds.append(_normalize_fund(f, dm))
    return funds


def fetch_funds(quiet=False):
    """Fetch fresh fund data from RBC GAM APIs."""
    if not quiet:
        print("Fetching fund data from RBC GAM...", file=sys.stderr)
    fds = fetch_json(FDS_URL)
    dotcms = fetch_json(DOTCMS_URL)
    funds = _merge_funds(fds, dotcms)
    if not quiet:
        print(f"Loaded {len(funds)} funds.", file=sys.stderr)
    return funds


def load_cached_funds(fds_path="rbcgam_fds_fund_data.json",
                      dotcms_path="rbcgam_dotcms_fund_data.json", quiet=False):
    """Load fund data from cached JSON files."""
    with open(fds_path) as f1, open(dotcms_path) as f2:
        fds_raw = json.load(f1)
        dotcms_raw = json.load(f2)
    fds = fds_raw["fundData"] if isinstance(fds_raw, dict) and "fundData" in fds_raw else fds_raw
    dotcms = dotcms_raw["fundData"] if isinstance(dotcms_raw, dict) and "fundData" in dotcms_raw else dotcms_raw
    funds = _merge_funds(fds, dotcms)
    if not quiet:
        print(f"Loaded {len(funds)} funds from cache.", file=sys.stderr)
    return funds


def get_funds(cached=False, quiet=False):
    """Load funds from cache or API. Falls back to API if cache missing."""
    if cached:
        try:
            return load_cached_funds(quiet=quiet)
        except FileNotFoundError:
            if not quiet:
                print("Cache not found, fetching fresh data...", file=sys.stderr)
    return fetch_funds(quiet=quiet)


def filter_series_f(funds):
    """Filter to only Series F (not FT5/FT8 variants)."""
    return [f for f in funds if f["series"] == "F"]


def build_fund_lookup(funds):
    """Build a dict mapping fund code -> fund dict."""
    return {f["code"]: f for f in funds}
