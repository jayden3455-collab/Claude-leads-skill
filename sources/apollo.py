"""Apollo.io People Search API source."""

import os
from typing import Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

APOLLO_BASE = "https://api.apollo.io/api/v1"


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Api-Key": os.environ["APOLLO_API_KEY"],
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def reveal_person(person_id: str) -> dict[str, Any]:
    """Fetch full contact data for a person ID returned by api_search."""
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{APOLLO_BASE}/people/match",
            headers=_headers(),
            json={"id": person_id, "reveal_personal_emails": False},
        )
        resp.raise_for_status()
        return resp.json().get("person", {})


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def search_people(
    job_titles: list[str],
    industries: list[str] | None = None,
    employee_ranges: list[str] | None = None,
    locations: list[str] | None = None,
    keywords: list[str] | None = None,
    page: int = 1,
    per_page: int = 100,
) -> dict[str, Any]:
    """
    Search Apollo for people matching ICP criteria.

    employee_ranges examples: ["1,10", "11,50", "51,200", "201,500", "501,1000", "1001,5000"]
    """
    payload: dict[str, Any] = {
        "page": page,
        "per_page": per_page,
        "person_titles": job_titles,
        "contact_email_status": ["verified", "unverified", "likely to engage"],
    }

    if industries:
        payload["q_organization_industry_tag_names"] = industries
    if employee_ranges:
        payload["organization_num_employees_ranges"] = employee_ranges
    if locations:
        payload["person_locations"] = locations
    if keywords:
        payload["q_keywords"] = " ".join(keywords)

    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{APOLLO_BASE}/mixed_people/api_search",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


def extract_leads(apollo_response: dict[str, Any], enrich: bool = True) -> list[dict[str, Any]]:
    """Normalise Apollo people records into a flat lead dict."""
    leads = []
    for stub in apollo_response.get("people", []):
        person_id = stub.get("id", "")
        person = stub

        if enrich and person_id:
            try:
                person = reveal_person(person_id)
            except Exception:
                pass

        org = person.get("organization") or {}
        email = (person.get("email") or "").strip()

        lead = {
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", person.get("last_name_obfuscated", "")),
            "full_name": person.get("name", f"{person.get('first_name','')} {person.get('last_name','')}".strip()),
            "email": email,
            "title": person.get("title", ""),
            "linkedin_url": person.get("linkedin_url", ""),
            "company": org.get("name", ""),
            "company_domain": org.get("primary_domain", ""),
            "company_size": org.get("estimated_num_employees", ""),
            "industry": org.get("industry", ""),
            "location": ", ".join(filter(None, [person.get("city", ""), person.get("country", "")])),
            "phone": (person.get("phone_numbers") or [{}])[0].get("raw_number", "") if person.get("phone_numbers") else "",
            "source": "apollo",
            "email_status": person.get("email_status", ""),
        }
        leads.append(lead)
    return leads
