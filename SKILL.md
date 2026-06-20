---
name: leads
description: >
  AI-powered B2B lead scraping pipeline. Scrape → ICP filter → email verify → personalize → CSV.
  Use when the user asks to scrape leads, find contacts, pull a lead list, run the pipeline,
  get emails for a niche, build a prospect list, or target any ICP with cold email outreach.
  Triggers on: "scrape leads", "find leads", "pull contacts", "run pipeline", "get emails for",
  "prospect list", "lead list", "cold email targets", "AI Ark", "Million Verifier", "ICP scrape".
---

# Lead Pipeline Skill

Full automated pipeline: **scrape → ICP filter → email verify → personalize → CSV**

Pipeline lives at `lead-agent/pipeline.py`. All leads export to `lead-agent/output/`.

---

## Setup (one-time per machine)

```bash
cd lead-agent
pip3 install -r requirements.txt
cp .env.example .env
# Fill in the three required keys (see below)
Required API keys (fill into lead-agent/.env)
Key	Where to get it	Purpose
ANTHROPIC_API_KEY	console.anthropic.com → API Keys	ICP filter + personalization
AI_ARK_API_KEY	ai-ark.com → Developer Portal	Lead scraping database
MILLION_VERIFIER_API_KEY	millionverifier.com → API	Email verification
Never hardcode keys — always use the .env file.

Running the pipeline

cd lead-agent
python3 pipeline.py "<ICP description>" <max_leads> [personalization_style]
Arguments
Arg	Required	Description
<ICP description>	Yes	Plain-English description of who to target
<max_leads>	Yes	Hard cap on leads to process. = AI Ark credits spent.
[personalization_style]	No	case_study (default), top_service, top_competitor, none
Credit math
Each lead processed through email export = 1 AI Ark credit
Set max_leads to stay under your credit budget
Safe default: 9000 (leaves buffer in a 10k-credit account)
Typical email hit rate: 8–13% depending on niche
Example invocations

# Boutique M&A advisory firms, US, decision makers
python3 pipeline.py "Buy-side M&A advisory firms in the US, company size 5-100 employees, decision makers: Managing Partner, Managing Director, Partner, Principal, CEO, Founder" 9000

# PR agencies, broader company size
python3 pipeline.py "PR agencies and public relations firms in the US, company size 5-200 employees, decision makers: CEO, Founder, Owner, Partner, Managing Director, Director, VP, President" 9000

# Podcasting agencies
python3 pipeline.py "Podcasting agencies and podcast production companies in the US, company size 5-100 employees, decision makers: CEO, Founder, Owner, Director" 5000 case_study

# No personalization (faster, cheaper on Claude tokens)
python3 pipeline.py "SaaS companies, US, 10-200 employees, founders and CEOs" 9000 none
Pipeline stages
Stage	What happens	Output
1. Scrape	Claude converts ICP → AI Ark filters, fetches profiles + emails	output/checkpoints/01_scraped_*.csv
2. ICP filter	Claude Haiku scores each lead PASS/FAIL against the ICP	output/checkpoints/02_icp_filtered_*.csv
3. Email verify	Million Verifier bulk-verifies all emails, keeps ok + catch_all	output/checkpoints/03_verified_*.csv
4. Personalize	Visits each company website, extracts top case study or service	Final CSV
5. Export	Final CSV lands in output/pipeline_<timestamp>.csv	output/pipeline_*.csv
Output CSV columns
First Name, Last Name, Full Name, Email, Email Status, Title, Seniority, Department, LinkedIn URL, Person Location, Person City, Person State, Person Country, Company, Company Domain, Company LinkedIn, Company Size, Company Industry, Company HQ City, Company HQ Country, ICP Match, Personalization, Top Competitor

How to pick max_leads and ICP
Company size guidance:

Too small to have budget: under 5 employees
Sweet spot for cold email clients: 5–100 employees
Has in-house teams: 200+ employees
Niche pool sizes (AI Ark, approximate):

Hyper-niche (M&A advisory, podcasting agencies): 3,000–5,000 people
Mid-size niche (PR agencies): 10,000–20,000 people
Broad (marketing agencies, SaaS): 50,000+ people
Expected yield per 9,000 credits:

8–13% email hit rate → 720–1,170 with emails
ICP filter removes ~40–60% → 288–700 pass
MV verification removes ~1–5% → 250–680 verified leads
To hit 2,000+ verified leads, either:

Run multiple niches and merge the CSVs
Target a broad niche with a large pool
When a run finishes
Report:

Niche targeted
Credits used (= max_leads capped at pool size)
Final verified lead count
Output file path
If the pool is smaller than max_leads, credits used = pool size (AI Ark stops at last page).

Gotchas
Email hit rate is not 100% — AI Ark only has emails for 8–13% of people in most niches. This is normal. The rest are scraped as profiles but dropped before ICP filtering.
Million Verifier can queue-delay — small batches (<200 emails) sometimes sit at 0% for 20–30 minutes before jumping to done. Don't kill the process.
catch_all emails are kept — MV pipeline keeps both ok and catch_all statuses. Only ok emails should go into cold email campaigns. Filter by Email Status = ok before uploading to Smartlead/PlusVibe.
AI Ark credits are spent on export, not search — browsing profile pages is free; the /people/export/single call (which fetches the email) costs 1 credit each.
Never kill a running pipeline — credits are already spent at the scrape stage. Killing mid-run orphans leads that are in the checkpoint but won't make it to the final CSV. Always let it finish.
Checkpoints are your safety net — if the pipeline crashes after step 2, the ICP-filtered leads are saved. You can re-run verification manually against 02_icp_filtered_*.csv.
python3, not python — the system command is python3. python is not aliased on macOS by default.
