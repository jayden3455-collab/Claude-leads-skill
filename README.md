# Claude-leads-skill
This skill helps you: 1. scrape your leads 2. confirm your ICP 3. validate them with Million Verifier 4. add any personalizations that you want to your list Fully automated with Claude Code
# Claude Leads Skill

A Claude Code skill that turns a plain-English description of who you want to target into a clean CSV of verified, personalized B2B leads — fully automated.

**Pipeline:** Scrape → ICP Filter → Email Verify → Personalize → CSV

---

## Install

Paste this in your terminal:

```bash
mkdir -p ~/.claude/skills/leads && curl -fsSL https://raw.githubusercontent.com/jayden3455-collab/Claude-leads-skill/main/SKILL.md -o ~/.claude/skills/leads/SKILL.md

What you need
3 API keys — all have free tiers or pay-as-you-go:

Tool	Get your key	What it does
Claude (Anthropic)	console.anthropic.com	ICP filtering + personalization
AI Ark	ai-ark.com	Lead database (pay per credit)
Million Verifier	millionverifier.com	Email verification
Add them to a .env file in your project:


ANTHROPIC_API_KEY=your_key_here
AI_ARK_API_KEY=your_key_here
MILLION_VERIFIER_API_KEY=your_key_here
Usage
Once installed, open any project in Claude Code and run:


/leads
Claude will ask what leads you want, then run the full pipeline automatically.

Or run the pipeline directly:


python3 pipeline.py "PR agencies in the US, 5-200 employees, CEOs and founders" 5000
How it works
You describe your target in plain English
Claude converts it into AI Ark search filters
AI Ark scrapes matching people + emails (1 credit per email fetched)
Claude filters out anyone who doesn't actually match your ICP
Million Verifier confirms which emails are deliverable
Claude visits each company website and writes a personalization line
Final CSV exported — ready to upload to any cold email tool
Credit math
1 AI Ark credit = 1 person's email fetched
Typical email hit rate: 8–13% of scraped profiles have emails
At 9,000 credits you can expect 250–680 verified leads depending on niche
Niche industries (M&A, podcasting): smaller pools (~3,000–5,000 total)
Broad industries (PR, marketing agencies): larger pools (10,000–50,000+)
Output
A CSV with: name, email, email status, title, LinkedIn URL, company, company size, industry, location, and a personalization line pulled from their website.

Built by VelocityFlow


