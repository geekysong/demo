"""Live XRPL marketplace discovery for the two Relay demo data sources.

The real services below are listed in t54's XRPL AI Hub / Agora and expose
their input schema plus a sample output in the x402 v2 ``PAYMENT-REQUIRED``
header.  Their real payment rails are XRPL mainnet (``xrpl:0``), while this
demo intentionally remains on testnet.  Relay therefore uses the real live
metadata for discovery and policy evaluation, then purchases a clearly
labelled local testnet mirror which returns the advertised sample payload.

No request made by this module carries a payment signature, so discovery
cannot spend funds.
"""

from __future__ import annotations

import base64
import json
from copy import deepcopy

import requests


DIRECTORY_URL = "https://api.xrpl-ai.org/discovery/resources"

SOURCES = [
    {
        "id": "T54-LEI",
        "name": "CompliancePulse · Global LEI lookup",
        "category": "business_registration_status",
        "source_url": "https://compliancepulse.theaslangroupllc.com/api/validate/lei",
        "probe_params": {"name": "Volkswagen", "country": "DE"},
        "testnet_path": "/testnet-mirror/lei",
        "fallback_description": (
            "Global LEI lookup and legal-entity search against GLEIF; returns "
            "entity and registration status using deterministic source data."
        ),
        "fallback_input": {
            "type": "http",
            "method": "GET",
            "queryParams": {"lei": "HWUPKR0MPOU8FGXBT394", "name": "Volkswagen", "country": "DE"},
        },
        "fallback_sample": {
            "mode": "lookup",
            "lei": "HWUPKR0MPOU8FGXBT394",
            "found": True,
            "legal_name": "Apple Inc.",
            "entity_status": "ACTIVE",
            "registration_status": "ISSUED",
            "usable": True,
            "jurisdiction": "US-CA",
            "next_renewal": "2027-03-08T17:27:20Z",
            "source": "GLEIF (Global LEI Foundation)",
            "deterministic": True,
        },
    },
    {
        "id": "T54-BLS",
        "name": "MacroPulse · BLS wage benchmarks",
        "category": "industry_income_benchmarks",
        "source_url": "https://macropulse.theaslangroupllc.com/api/macro/bls-series",
        "probe_params": {"series": "wages"},
        "testnet_path": "/testnet-mirror/bls",
        "fallback_description": (
            "Official US labor statistics by BLS series ID; returns latest values, "
            "year-over-year changes, and observations deterministically."
        ),
        "fallback_input": {
            "type": "http",
            "method": "GET",
            "queryParams": {"series": "wages"},
        },
        "delivery_mode": "testnet_mirror_of_bls_historical_wage_sample",
        "sample_label": "BLS historical wage sample · May 2023 · not live vendor output",
        "sample_note": "Legal services, US national, all occupations. Historical demonstration data; does not satisfy a 30-day freshness requirement or verify an individual's income.",
        "fallback_sample": {
            "data_type": "industry_income_benchmarks",
            "metric": "industry_wages",
            "industry": {"name": "Legal services", "taxonomy": "NAICS", "code": "541100"},
            "occupation_scope": "All occupations (00-0000)",
            "geography": "US national",
            "period": "May 2023",
            "currency": "USD",
            "mean_annual_wage": 110650,
            "median_hourly_wage": 36.18,
            "mean_hourly_wage": 53.20,
            "source": "US Bureau of Labor Statistics · OEWS",
            "source_url": "https://www.bls.gov/oes/2023/may/naics4_541100.htm",
            "sample": True,
            "freshness_status": "historical_sample_not_validated_for_current_request",
            "usage_note": "Industry context only; not personal income verification. Annual mean is not annual median.",
        },
    },
]


def _decode_payment_required(value: str) -> dict:
    padded = value.strip() + "=" * (-len(value.strip()) % 4)
    return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))


def _mainnet_xrp_accept(challenge: dict) -> dict | None:
    for option in challenge.get("accepts", []):
        if option.get("network") == "xrpl:0" and option.get("asset") == "XRP":
            return option
    return None


def _fallback_candidate(source: dict, error: str | None = None) -> dict:
    return {
        "id": source["id"],
        "name": source["name"],
        "price_usd": 0.02,
        "price_drops": 20_000,
        "price_label": "0.02 XRP (20,000 drops)",
        # Demo proxy only: live 402 + directory presence. It is deliberately
        # named in the UI rather than presented as a vendor-supplied score.
        "trust_score": 80,
        "trust_basis": "demo proxy: XRPL AI Hub listing + live HTTP 402",
        "freshness_days": 0,
        "freshness_basis": "endpoint checked live at discovery; payload freshness validated after delivery",
        "schema": "x402 Bazaar v2 · JSON",
        "category": source["category"],
        "source_url": source["source_url"],
        "source_network": "xrpl:0",
        "source_asset": "XRP",
        "source_pay_to": None,
        "marketplace": "t54 XRPL AI Hub / Agora",
        "marketplace_directory": DIRECTORY_URL,
        "discovery_status": "fallback" if error else "fixture",
        "discovery_error": error,
        "payment_mode": "testnet_mirror",
        "testnet_path": source["testnet_path"],
        "description": source["fallback_description"],
        "sample_input": deepcopy(source["fallback_input"]),
        "sample_data": deepcopy(source["fallback_sample"]),
        "delivery_mode": source.get("delivery_mode", "testnet_mirror_of_live_bazaar_sample"),
        "sample_label": source.get("sample_label", "Stored vendor sample for Testnet delivery"),
        "sample_note": source.get("sample_note", "Sample output only; not a live applicant lookup."),
        "supports_reason_codes": True,
        "deterministic_output": True,
    }


def fetch_candidate(source: dict, timeout: float = 8.0) -> dict:
    """Probe one unpaid resource and normalize its Bazaar declaration."""
    response = requests.get(source["source_url"], params=source["probe_params"], timeout=timeout)
    if response.status_code != 402:
        raise RuntimeError(f"expected HTTP 402, received {response.status_code}")

    encoded = response.headers.get("PAYMENT-REQUIRED") or response.headers.get("payment-required")
    if not encoded:
        raise RuntimeError("HTTP 402 response did not include PAYMENT-REQUIRED")

    challenge = _decode_payment_required(encoded)
    accepted = _mainnet_xrp_accept(challenge)
    if not accepted:
        raise RuntimeError("resource does not advertise an xrpl:0 XRP payment option")

    bazaar = challenge.get("extensions", {}).get("bazaar", {})
    info = bazaar.get("info", {})
    resource = challenge.get("resource", {})
    candidate = _fallback_candidate(source)
    candidate.update(
        price_drops=int(accepted["amount"]),
        price_label=f"{int(accepted['amount']) / 1_000_000:g} XRP ({int(accepted['amount']):,} drops)",
        source_pay_to=accepted.get("payTo"),
        description=resource.get("description") or candidate["description"],
        schema="x402 Bazaar v2 · " + (resource.get("mimeType") or "application/json"),
        advertised_input=info.get("input"),
        advertised_sample=info.get("output", {}).get("example"),
        discovery_status="live",
        discovery_error=None,
    )
    return candidate


def load_candidates(timeout: float = 8.0) -> list[dict]:
    """Load both live candidates, falling back independently if one is down."""
    candidates = []
    for source in SOURCES:
        try:
            candidates.append(fetch_candidate(source, timeout=timeout))
        except Exception as exc:
            candidates.append(_fallback_candidate(source, error=str(exc)))
    return candidates


def fallback_candidates() -> list[dict]:
    return [_fallback_candidate(source) for source in SOURCES]


def sample_for(candidate_id: str) -> dict:
    for candidate in fallback_candidates():
        if candidate["id"] == candidate_id:
            return candidate["sample_data"]
    raise KeyError(candidate_id)


if __name__ == "__main__":
    print(json.dumps(load_candidates(), indent=2))
