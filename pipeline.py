#!/usr/bin/env python3
"""
AI Lead Pipeline
================
Full automated pipeline: scrape → ICP filter → email verify → website personalization → CSV

Usage:
  python3 pipeline.py "2000 M&A advisory firms, founders/CEOs/managing directors, 2-50 employees"

Steps:
  1. Scrape leads from AI Ark (with emails)
  2. ICP filter — Claude drops anything that doesn't match
  3. Email verification — Million Verifier, keeps ok + catch_all
  4. Website personalization — visit company site, extract top case study or top service
     Output always: "prospects looking for [X]"
  5. Export final CSV
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Any

import anthropic
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# ── Clients & constants ────────────────────────────────────────────────────────
CLAUDE  = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MV_KEY  = os.environ.get("MILLION_VERIFIER_API_KEY", "")
ARK_KEY = os.environ.get("AI_ARK_API_KEY", "")
ARK_BASE = "https://api.ai-ark.com/api/developer-portal/v1"

FAST_MODEL  = "claude-haiku-4-5-20251001"
SMART_MODEL = "claude-sonnet-4-6"

CSV_HEADERS = [
    "First Name", "Last Name", "Full Name",
    "Email", "Email Status",
    "Title", "Seniority", "Department",
    "LinkedIn URL",
    "Person Location", "Person City", "Person State", "Person Country",
    "Company", "Company Domain", "Company LinkedIn",
    "Company Size", "Company Industry",
    "Company HQ City", "Company HQ Country",
    "ICP Match",
    "Personalization",
    "Top Competitor",
]

CHECKPOINT_DIR = os.path.join(os.path.dirname(__file__), "output", "checkpoints")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _n(d, *keys, default=""):
    val = d
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k)
        if val is None:
            return default
    return val if val is not None else default


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def checkpoint(leads: list[dict], label: str) -> None:
    """Save intermediate results to disk after each pipeline step."""
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(CHECKPOINT_DIR, f"{label}_{ts}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)
    log(f"  Checkpoint: {path} ({len(leads)} leads)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — SCRAPE
# ══════════════════════════════════════════════════════════════════════════════

def build_filters(icp: str, max_leads: int) -> tuple[dict, int]:
    """Ask Claude to convert plain-English ICP into AI Ark filter JSON."""
    log("Building AI Ark filters from ICP description...")

    prompt = f"""Convert this ICP description into an AI Ark people search filter JSON.

ICP: {icp}

Return ONLY valid JSON with this structure (use only fields that apply):
{{
  "contact": {{
    "seniority": {{"any": {{"include": ["founder","owner","c_suite","partner"]}}}},
    "location": {{"any": {{"include": ["United States"]}}}},
    "experience": {{
      "current": {{
        "title": {{
          "any": {{
            "include": {{
              "mode": "SMART",
              "content": ["CEO","founder","managing director"]
            }}
          }}
        }}
      }}
    }}
  }},
  "account": {{
    "industries": {{"any": {{"include": {{"mode": "SMART", "content": ["investment banking"]}}}}}},
    "employeeSize": {{"type": "RANGE", "range": [{{"start": 2, "end": 50}}]}},
    "location": {{"any": {{"include": ["United States"]}}}}
  }}
}}

Rules:
- seniority values: founder, owner, c_suite, partner, director, manager, senior
- For title content use SMART mode with plain job title words
- employeeSize range: small/boutique = 2-50, mid = 2-200
- Only include location filter if ICP specifies geography
- Return ONLY the JSON, no explanation"""

    resp = CLAUDE.messages.create(
        model=FAST_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw), max_leads


def ark_post(path: str, body: dict) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{ARK_BASE}{path}",
                   headers={"X-TOKEN": ARK_KEY, "Content-Type": "application/json"},
                   json=body)
        r.raise_for_status()
        return r.json()


async def get_email_async(client: httpx.AsyncClient, person_id: str, sem: asyncio.Semaphore) -> str:
    async with sem:
        for attempt in range(6):
            try:
                r = await client.post(
                    f"{ARK_BASE}/people/export/single",
                    headers={"X-TOKEN": ARK_KEY, "Content-Type": "application/json"},
                    json={"id": person_id},
                    timeout=20,
                )
                if r.status_code == 404:
                    return ""
                if r.status_code == 429:
                    await asyncio.sleep((2 ** attempt) + 0.5)
                    continue
                r.raise_for_status()
                outputs = (_n(r.json(), "email") or {}).get("output") or []
                return outputs[0].get("address", "") if outputs else ""
            except httpx.TimeoutException:
                await asyncio.sleep((2 ** attempt) * 0.5)
            except Exception:
                return ""
        return ""


def extract_lead(person: dict, email: str = "") -> dict:
    profile = person.get("profile") or {}
    location = person.get("location") or {}
    link = person.get("link") or {}
    company = person.get("company") or {}
    cs = company.get("summary") or {}
    cl = company.get("link") or {}
    hq = _n(company, "location", "headquarter") or {}
    dept = person.get("department") or {}

    return {
        "First Name": profile.get("first_name", ""),
        "Last Name": profile.get("last_name", ""),
        "Full Name": profile.get("full_name", ""),
        "Email": email,
        "Email Status": "",
        "Title": profile.get("title", ""),
        "Seniority": dept.get("seniority", ""),
        "Department": ", ".join(dept.get("departments") or []),
        "LinkedIn URL": link.get("linkedin", ""),
        "Person Location": location.get("default", ""),
        "Person City": location.get("city", ""),
        "Person State": location.get("state", ""),
        "Person Country": location.get("country", ""),
        "Company": cs.get("name", ""),
        "Company Domain": cl.get("domain", ""),
        "Company LinkedIn": cl.get("linkedin", ""),
        "Company Size": _n(cs, "staff", "total"),
        "Company Industry": cs.get("industry", ""),
        "Company HQ City": hq.get("city", ""),
        "Company HQ Country": hq.get("country", ""),
        "ICP Match": "",
        "Personalization": "",
        "Top Competitor": "",
    }


async def scrape(filters: dict, max_leads: int) -> list[dict]:
    raw = []
    page = 0
    log(f"Scraping up to {max_leads} leads from AI Ark...")

    while len(raw) < max_leads:
        try:
            data = ark_post("/people", {"page": page, "size": min(100, max_leads - len(raw)), **filters})
        except httpx.HTTPStatusError as e:
            log(f"  Search error page {page}: {e.response.status_code} — {e.response.text[:150]}")
            break
        except Exception as e:
            log(f"  Search failed page {page}: {e}")
            break

        batch = data.get("content", [])
        if not batch:
            break

        raw.extend(batch)
        log(f"  Page {page + 1}: +{len(batch)} → {len(raw)} (pool: {data.get('totalElements','?')})")

        if data.get("last", True) or len(batch) < 100:
            break
        page += 1
        time.sleep(0.25)

    log(f"Fetching emails for {len(raw)} leads concurrently (5 in parallel)...")
    CONCURRENCY = 5
    sem = asyncio.Semaphore(CONCURRENCY)
    emails: list[str] = [""] * len(raw)
    found_count = [0]

    async with httpx.AsyncClient() as client:
        async def fetch_one(i: int, pid: str):
            result = await get_email_async(client, pid, sem) if pid else ""
            emails[i] = result
            if result:
                found_count[0] += 1

        tasks = [fetch_one(i, p.get("id", "")) for i, p in enumerate(raw)]
        done = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            done += 1
            if done % 500 == 0 or done == len(raw):
                pct = round(found_count[0] / done * 100) if done else 0
                log(f"  {done}/{len(raw)} enriched — {found_count[0]} emails found ({pct}%)")

    leads = [extract_lead(person, email=emails[i]) for i, person in enumerate(raw)]
    log(f"Scrape complete: {len(leads)} leads, {found_count[0]} with emails.")
    checkpoint(leads, "01_scraped")
    return leads


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — ICP FILTER
# ══════════════════════════════════════════════════════════════════════════════

def _score_batch(batch: list[dict], icp: str) -> list[str]:
    """Score a single batch against ICP. Runs in a thread via asyncio.to_thread."""
    numbered = "\n".join(
        f"{j+1}. Title: {l['Title']} | Company: {l['Company']} | Industry: {l['Company Industry']} | Size: {l['Company Size']} | Seniority: {l['Seniority']}"
        for j, l in enumerate(batch)
    )
    prompt = f"""You are an ICP qualifier. Score each lead as PASS or FAIL against this ICP:

ICP: {icp}

Leads:
{numbered}

Reply with ONLY a JSON array of {len(batch)} strings, each "PASS" or "FAIL", in order.
Example: ["PASS","FAIL","PASS"]"""

    try:
        resp = CLAUDE.messages.create(
            model=FAST_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else ["PASS"] * len(batch)
    except Exception:
        return ["PASS"] * len(batch)


async def icp_filter(leads: list[dict], icp: str) -> list[dict]:
    """Drop no-email leads first, then score the rest with concurrent Claude batches."""
    with_email = [l for l in leads if l.get("Email")]
    skipped = len(leads) - len(with_email)
    if skipped:
        log(f"  Skipping {skipped} leads with no email before ICP filter.")

    log(f"ICP filtering {len(with_email)} leads (10 concurrent batches of 50)...")

    BATCH = 50
    MAX_CONCURRENT = 10
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    batches = [with_email[i:i + BATCH] for i in range(0, len(with_email), BATCH)]
    scores_list: list[list[str] | None] = [None] * len(batches)

    async def score_one(idx: int, batch: list[dict]):
        async with sem:
            scores_list[idx] = await asyncio.to_thread(_score_batch, batch, icp)

    await asyncio.gather(*[score_one(i, b) for i, b in enumerate(batches)])

    passed = []
    for batch, scores in zip(batches, scores_list):
        for lead, score in zip(batch, scores or []):
            lead["ICP Match"] = score
            if score == "PASS":
                passed.append(lead)

    log(f"ICP filter: {len(passed)}/{len(with_email)} passed.")
    checkpoint(passed, "02_icp_filtered")
    return passed


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — EMAIL VERIFICATION (Million Verifier)
# ══════════════════════════════════════════════════════════════════════════════

MV_SINGLE    = "https://api.millionverifier.com/api/v3"
MV_BULK_BASE = "https://bulkapi.millionverifier.com/bulkapi/v2"

MV_KEEP = {"ok", "catch_all"}


def _mv_upload(emails: list[str]) -> str:
    content = "\n".join(emails).encode()
    with httpx.Client(timeout=60) as c:
        r = c.post(
            f"{MV_BULK_BASE}/upload",
            params={"key": MV_KEY},
            files={"file_contents": ("emails.txt", content, "text/plain")},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"MV upload error: {data['error']}")
        return str(data["file_id"])


def _mv_poll(file_id: str) -> None:
    log(f"  Waiting for Million Verifier to finish (file_id={file_id})...")
    while True:
        with httpx.Client(timeout=30) as c:
            r = c.get(f"{MV_BULK_BASE}/fileinfo", params={"key": MV_KEY, "file_id": file_id})
            r.raise_for_status()
            data = r.json()
        status = data.get("status", "")
        pct = data.get("percent", 0)
        if status == "finished":
            log(f"  Million Verifier done — {data.get('ok',0)} ok, {data.get('invalid',0)} invalid")
            return
        if status == "error":
            raise RuntimeError(f"Million Verifier error: {data}")
        print(f"\r  Processing... {pct}%  ", end="", flush=True)
        time.sleep(3)


def _mv_download(file_id: str) -> dict[str, str]:
    with httpx.Client(timeout=60) as c:
        r = c.get(f"{MV_BULK_BASE}/download",
                  params={"key": MV_KEY, "file_id": file_id, "filter": "all"})
        r.raise_for_status()
        lines = r.text.strip().splitlines()

    result = {}
    for line in lines:
        parts = line.split(",")
        if len(parts) >= 3:
            email  = parts[0].strip().strip('"').lower()
            status = parts[2].strip().strip('"').lower()
            if email and email != "email":
                result[email] = status
    return result


def verify_emails(leads: list[dict]) -> list[dict]:
    with_email = [l for l in leads if l.get("Email")]
    without = len(leads) - len(with_email)
    log(f"Verifying {len(with_email)} emails via Million Verifier ({without} had no email — dropped)...")

    if not with_email:
        return []

    emails = [l["Email"] for l in with_email]

    try:
        file_id = _mv_upload(emails)
        _mv_poll(file_id)
        result_map = _mv_download(file_id)
    except Exception as e:
        log(f"  Million Verifier failed: {e} — keeping all emails unverified")
        for lead in with_email:
            lead["Email Status"] = "unverified"
        return with_email

    verified = []
    for lead in with_email:
        status = result_map.get(lead["Email"].lower(), "unknown")
        lead["Email Status"] = status
        if status in MV_KEEP:
            verified.append(lead)

    kept = len(verified)
    log(f"Email verification: {kept}/{len(with_email)} kept (ok + catch_all).")
    checkpoint(verified, "03_verified")
    return verified


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — WEBSITE PERSONALIZATION
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_page(client: httpx.AsyncClient, url: str) -> str:
    """Fetch a single URL and return stripped text (max 6000 chars)."""
    try:
        r = await client.get(url, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return ""
        text = r.text
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:6000]
    except Exception:
        return ""


async def fetch_website_content(client: httpx.AsyncClient, domain: str) -> str:
    """Fetch all candidate pages in parallel, return best content."""
    if not domain:
        return ""
    domain = domain.strip().rstrip("/")
    if not domain.startswith("http"):
        domain = f"https://{domain}"

    urls = [
        domain,
        f"{domain}/case-studies",
        f"{domain}/case-study",
        f"{domain}/success-stories",
        f"{domain}/services",
        f"{domain}/solutions",
    ]
    results = await asyncio.gather(*[fetch_page(client, u) for u in urls], return_exceptions=True)
    texts = [r if isinstance(r, str) else "" for r in results]
    homepage, cs1, cs2, cs3, svc1, svc2 = texts

    case_study = cs1 or cs2 or cs3
    services   = svc1 or svc2
    return case_study or services or homepage


PERSONALIZATION_PROMPTS = {
    "case_study": (
        'output a single line starting with exactly "prospects looking for" followed by their TOP CASE STUDY '
        '— e.g. "prospects looking for their case study helping a fintech company cut onboarding time by 60%". '
        'If no case study found, fall back to their top service.'
    ),
    "top_service": (
        'output a single line starting with exactly "prospects looking for" followed by their MAIN SERVICE OFFERING '
        '— e.g. "prospects looking for executive search for private equity portfolio companies". '
        'Be specific — pull real service language from their website.'
    ),
    "clean_name": (
        'output a clean, natural version of the company name with no legal suffixes (remove LLC, Inc, Corp, Ltd, Co., etc.) '
        '— e.g. input "Apex Recruiting Solutions, LLC" → output "Apex Recruiting Solutions". '
        'Do NOT start with "prospects looking for".'
    ),
    "top_competitor": (
        'identify the single most well-known direct competitor to this company — '
        'the brand their customers would most likely compare them to or switch to. '
        'Output ONLY the competitor company name, nothing else. No descriptions, no "vs.", just the name. '
        '— e.g. input: Fellow Products (premium coffee equipment) → output: Breville'
    ),
    "custom": "",
}


def personalize_batch(leads_with_content: list[tuple[dict, str]], icp: str,
                      style: str = "case_study", custom_prompt: str = "") -> list[str]:
    """Score a single personalization batch. Runs in a thread via asyncio.to_thread."""
    if not leads_with_content:
        return []

    style_instruction = custom_prompt if style == "custom" else PERSONALIZATION_PROMPTS.get(style, PERSONALIZATION_PROMPTS["case_study"])

    items = []
    for i, (lead, content) in enumerate(leads_with_content, 1):
        snippet = content[:2000] if content else "(no website content available)"
        items.append(
            f"Lead {i}: {lead['Company']} ({lead['Company Industry']}, {lead['Company Size']} employees)\n"
            f"Website content: {snippet}\n"
        )

    prompt = f"""You are writing personalization data for cold emails targeting {icp}.

For each lead below, {style_instruction}

Rules:
- ALWAYS output something — no blanks ever
- Be specific — use real details from their website, not generic phrases
- If no website content is available, infer from company name and industry
- Keep each output under 20 words
- Output ONLY a JSON array of {len(leads_with_content)} strings, nothing else

{chr(10).join(items)}"""

    try:
        resp = CLAUDE.messages.create(
            model=FAST_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        results = json.loads(match.group(0)) if match else []
        out = []
        for r in results:
            r = r.strip()
            if style in ("case_study", "top_service") and not r.lower().startswith("prospects looking for"):
                r = "prospects looking for " + r
            out.append(r)
        return out
    except Exception:
        fallback = (
            f"prospects looking for {leads_with_content[0][0].get('Company Industry') or 'services'}"
            if style in ("case_study", "top_service")
            else leads_with_content[0][0].get("Company", "")
        )
        return [fallback for _ in leads_with_content]


async def personalize_all(leads: list[dict], icp: str,
                          style: str = "case_study", custom_prompt: str = "") -> list[dict]:
    """Fetch all websites concurrently with a shared client, then run Claude batches concurrently."""
    if style == "none":
        log("Skipping personalization.")
        return leads

    log(f"Fetching websites for {len(leads)} leads (concurrent, shared client)...")

    FETCH_CONCURRENCY  = 50
    CLAUDE_BATCH       = 20
    CLAUDE_CONCURRENCY = 10

    contents: list[str] = [""] * len(leads)
    fetch_sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
    limits  = httpx.Limits(max_connections=150, max_keepalive_connections=50)

    async with httpx.AsyncClient(headers=headers, verify=False, limits=limits) as client:
        async def bounded_fetch(i: int, domain: str):
            async with fetch_sem:
                contents[i] = await fetch_website_content(client, domain)

        tasks   = [bounded_fetch(i, l.get("Company Domain", "")) for i, l in enumerate(leads)]
        fetched = 0
        for coro in asyncio.as_completed(tasks):
            await coro
            fetched += 1
            if fetched % 100 == 0 or fetched == len(leads):
                log(f"  Fetched {fetched}/{len(leads)} websites")

    col = "Top Competitor" if style == "top_competitor" else "Personalization"
    log(f"Personalizing {len(leads)} leads via Claude ({CLAUDE_CONCURRENCY} concurrent batches)...")

    claude_sem = asyncio.Semaphore(CLAUDE_CONCURRENCY)
    batches    = [(i, leads[i:i + CLAUDE_BATCH], contents[i:i + CLAUDE_BATCH])
                  for i in range(0, len(leads), CLAUDE_BATCH)]
    done_count = [0]

    async def process_batch(start: int, batch_leads: list[dict], batch_content: list[str]):
        async with claude_sem:
            pairs = list(zip(batch_leads, batch_content))
            lines = await asyncio.to_thread(personalize_batch, pairs, icp, style, custom_prompt)
            for j, line in enumerate(lines):
                if start + j < len(leads):
                    leads[start + j][col] = line
            for j in range(len(lines), len(batch_leads)):
                idx = start + j
                industry = leads[idx].get("Company Industry") or "their industry"
                leads[idx][col] = f"prospects looking for {industry} services" if col == "Personalization" else ""
            done_count[0] += len(batch_leads)
            if done_count[0] % (CLAUDE_BATCH * 5) < CLAUDE_BATCH or done_count[0] >= len(leads):
                log(f"  Personalized {min(done_count[0], len(leads))}/{len(leads)}")

    await asyncio.gather(*[process_batch(i, bl, bc) for i, bl, bc in batches])
    return leads


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════════════════

def export_csv(leads: list[dict], filename: str | None = None) -> str:
    if not leads:
        log("No leads to export.")
        return ""

    output_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(output_dir, exist_ok=True)

    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(output_dir, f"pipeline_{ts}.csv")

    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)

    log(f"Exported {len(leads)} leads → {filename}")
    return filename


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def run_pipeline(icp: str, max_leads: int,
                       personalization_style: str = "case_study",
                       custom_personalization: str = ""):
    log(f"=== AI Lead Pipeline ===")
    log(f"ICP: {icp}")
    log(f"Target: {max_leads} leads")
    log(f"Personalization: {personalization_style}\n")

    filters, _ = build_filters(icp, max_leads)
    log(f"AI Ark filters:\n{json.dumps(filters, indent=2)}\n")
    leads = await scrape(filters, max_leads)

    if not leads:
        log("No leads found. Exiting.")
        return

    leads = await icp_filter(leads, icp)
    if not leads:
        log("No leads passed ICP filter. Exiting.")
        return

    leads = verify_emails(leads)
    if not leads:
        log("No leads with valid emails. Exiting.")
        return

    leads = await personalize_all(leads, icp,
                                  style=personalization_style,
                                  custom_prompt=custom_personalization)

    log("\n=== Pipeline Complete ===")
    log(f"Total leads: {len(leads)}")
    log(f"With email: {sum(1 for l in leads if l.get('Email'))}")
    log(f"With personalization: {sum(1 for l in leads if l.get('Personalization'))}")

    export_csv(leads)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    icp = sys.argv[1]
    max_leads             = int(sys.argv[2]) if len(sys.argv) > 2 else 500
    personalization_style = sys.argv[3] if len(sys.argv) > 3 else "case_study"
    custom_personalization = sys.argv[4] if len(sys.argv) > 4 else ""

    asyncio.run(run_pipeline(icp, max_leads, personalization_style, custom_personalization))


if __name__ == "__main__":
    main()
