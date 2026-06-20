"""ICP (Ideal Customer Profile) scoring and filtering.

Each lead is scored 0-100 against the ICP criteria.
Leads below the threshold are dropped before email validation.
"""

from typing import Any
from pydantic import BaseModel, Field


class ICPCriteria(BaseModel):
    """Define your Ideal Customer Profile here."""

    # Required job title keywords (at least one must match)
    title_keywords: list[str] = Field(
        default_factory=list,
        description="e.g. ['CEO', 'Founder', 'Head of Marketing']",
    )

    # Required industries (at least one must match if set)
    industries: list[str] = Field(
        default_factory=list,
        description="e.g. ['SaaS', 'E-commerce', 'Real Estate']",
    )

    # Employee count range [min, max] — None means no limit
    min_employees: int | None = None
    max_employees: int | None = None

    # Required locations (at least one must match if set)
    locations: list[str] = Field(
        default_factory=list,
        description="e.g. ['United States', 'Canada', 'New York']",
    )

    # Keywords that must appear in title/company/industry
    required_keywords: list[str] = Field(default_factory=list)

    # Keywords that disqualify a lead
    exclude_keywords: list[str] = Field(default_factory=list)

    # Minimum ICP score (0-100) to keep a lead
    min_score: int = Field(default=60)


def _contains_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


def score_lead(lead: dict[str, Any], icp: ICPCriteria) -> int:
    """
    Score a lead 0-100 against ICP criteria.
    Points are allocated proportionally across criteria dimensions.
    """
    score = 0
    max_score = 0

    title = lead.get("title", "")
    industry = lead.get("industry", "")
    location = lead.get("location", "")
    company = lead.get("company", "")
    size_raw = lead.get("company_size", 0)

    try:
        size = int(size_raw) if size_raw else 0
    except (ValueError, TypeError):
        size = 0

    combined_text = f"{title} {industry} {company}"

    # ── Title match (30 pts) ────────────────────────────────────────────────
    if icp.title_keywords:
        max_score += 30
        if _contains_any(title, icp.title_keywords):
            score += 30

    # ── Industry match (25 pts) ─────────────────────────────────────────────
    if icp.industries and industry:
        max_score += 25
        if _contains_any(industry, icp.industries):
            score += 25

    # ── Company size match (20 pts) ─────────────────────────────────────────
    if (icp.min_employees is not None or icp.max_employees is not None) and size > 0:
        max_score += 20
        size_ok = True
        if icp.min_employees is not None and size < icp.min_employees:
            size_ok = False
        if icp.max_employees is not None and size > icp.max_employees:
            size_ok = False
        if size_ok:
            score += 20

    # ── Location match (15 pts) ─────────────────────────────────────────────
    if icp.locations and location:
        max_score += 15
        if _contains_any(location, icp.locations):
            score += 15

    # ── Required keywords (10 pts) ──────────────────────────────────────────
    if icp.required_keywords:
        max_score += 10
        if _contains_any(combined_text, icp.required_keywords):
            score += 10

    # Normalise to 0-100
    if max_score == 0:
        return 100  # No criteria set → keep everything
    normalised = int((score / max_score) * 100)

    # Hard disqualify on exclude keywords
    if icp.exclude_keywords and _contains_any(combined_text, icp.exclude_keywords):
        return 0

    return normalised


def filter_by_icp(
    leads: list[dict[str, Any]],
    icp: ICPCriteria,
) -> list[dict[str, Any]]:
    """Score each lead and return only those meeting the minimum score threshold."""
    qualified = []
    for lead in leads:
        s = score_lead(lead, icp)
        lead["icp_score"] = s
        if s >= icp.min_score:
            qualified.append(lead)
    return qualified


def deduplicate(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate leads by email, keeping the first occurrence."""
    seen: set[str] = set()
    unique = []
    for lead in leads:
        key = (lead.get("email") or "").lower().strip()
        if not key:
            key = (lead.get("linkedin_url") or "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(lead)
        elif not key:
            unique.append(lead)
    return unique
