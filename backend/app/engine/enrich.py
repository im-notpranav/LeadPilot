"""Enrichment (pure given provider data). MockEnrichmentProvider reads data/companies.json."""
from __future__ import annotations

from typing import Protocol


class EnrichmentProvider(Protocol):
    def lookup(self, domain: str) -> dict | None: ...
    def mx_valid(self, domain: str) -> bool: ...
    def is_disposable(self, domain: str) -> bool: ...
    def ip_country(self, ip: str | None) -> str | None: ...


class MockEnrichmentProvider:
    """Mocked firmographics, MX validation and IP geolocation from seed data. Real providers plug in here."""

    def __init__(self, cfg):
        self._companies = cfg.data.companies
        self._no_mx = cfg.data.no_mx_domains
        self._disposable = cfg.data.disposable_domains
        self._ip_geo = cfg.data.ip_geo

    def lookup(self, domain: str) -> dict | None:
        return self._companies.get(domain) if domain else None

    def mx_valid(self, domain: str) -> bool:
        if not domain:
            return True
        return domain not in self._no_mx

    def is_disposable(self, domain: str) -> bool:
        return bool(domain) and domain in self._disposable

    def ip_country(self, ip: str | None) -> str | None:
        if not ip:
            return None
        return self._ip_geo.get(ip.split(".")[0])


def employee_band(employees: int | None, cfg) -> str | None:
    if employees is None:
        return None
    for band in cfg.scoring.fit.company_size.bands:
        if band["max"] is None or employees <= band["max"]:
            return band["label"]
    return None


def segment_for(employees: int | None, cfg) -> str | None:
    if employees is None:
        return None
    for seg in cfg.assignment.segments:
        if seg["max"] is None or employees <= seg["max"]:
            return seg["name"]
    return None


def enrich(ident: dict, provider: EnrichmentProvider, cfg) -> dict | None:
    """Payload for the derived `lead_enriched` event, or None when there is nothing to enrich
    (free-mail with no website)."""
    domain = ident.get("domain")
    if not domain:
        return None
    company = provider.lookup(domain)
    if not company:
        return {"account_id": f"A-{domain}", "domain": domain, "found": False}
    return {
        "account_id": f"A-{domain}",
        "domain": domain,
        "found": True,
        "company_name": company["name"],
        "employees": company["employees"],
        "employee_band": employee_band(company["employees"], cfg),
        "industry": company["industry"],
        "revenue_band": company.get("revenue_band"),
        "hq_country": company.get("country"),
        "tech_stack": company.get("tech_stack", []),
        "funding_stage": company.get("funding_stage"),
    }
