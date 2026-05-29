"""
Demo Data — Pre-curated leads + emails for Natively AI
Loaded instantly via the "🎬 Load Demo" button so judges see full results without waiting.
"""

from datetime import datetime

_NOW = datetime.utcnow().isoformat() + "Z"

DEMO_LEADS = [
    {
        "id": "demo-lead-001",
        "company_name": "Landbase",
        "domain": "landbase.com",
        "industry": "AI Sales Automation",
        "geo": "US",
        "headcount": "11-50",
        "funding_stage": "Seed",
        "funding_amount": "$1M",
        "funding_date": "2025-03",
        "score": 92,
        "status": "new",
        "description": "Landbase uses AI agents to automate outbound sales. Raised $1M seed, building AI workflows.",
        "linkedin_url": "https://linkedin.com/company/landbase",
        "tech_stack": ["Python", "React", "OpenAI", "AWS"],
        "hiring_signals": ["Hiring ML Engineers", "Building AI Product"],
        "contacts": [{"name": "Oliver Sharpe", "title": "CEO", "linkedin": "https://linkedin.com/in/oliversharpe", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["AI-native product team", "Seed stage — open to new tools", "Hiring ML engineers = AI infra pain", "Small team = need to move fast"],
        "source_urls": ["https://techcrunch.com/landbase-1m-seed"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-002",
        "company_name": "Rho",
        "domain": "rho.co",
        "industry": "Fintech / Business Banking",
        "geo": "US",
        "headcount": "51-200",
        "funding_stage": "Series_A",
        "funding_amount": "$8.2M",
        "funding_date": "2025-01",
        "score": 87,
        "status": "new",
        "description": "Rho is an AI-powered business banking and spend management platform for startups.",
        "linkedin_url": "https://linkedin.com/company/rho-business-banking",
        "tech_stack": ["TypeScript", "Node.js", "PostgreSQL", "AWS"],
        "hiring_signals": ["Hiring AI/ML Engineers", "Hiring Product Managers"],
        "contacts": [{"name": "Alex Ioffe", "title": "CTO", "linkedin": "https://linkedin.com/in/alexioffe", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["Series A funded", "Building AI features internally", "100-200 employees = scaling pain", "Fintech needs fast iteration"],
        "source_urls": ["https://rho.co/blog/series-a"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-003",
        "company_name": "Growthlist",
        "domain": "growthlist.co",
        "industry": "B2B Data & Growth",
        "geo": "US",
        "headcount": "11-50",
        "funding_stage": "Series_B",
        "funding_amount": "$273K",
        "funding_date": "2025-04",
        "score": 84,
        "status": "new",
        "description": "Growthlist provides curated B2B company lists and growth signals. Data-driven, developer-friendly.",
        "linkedin_url": "https://linkedin.com/company/growthlist",
        "tech_stack": ["Python", "FastAPI", "React"],
        "hiring_signals": ["Hiring SDRs", "Hiring Marketing"],
        "contacts": [{"name": "James Moran", "title": "Founder", "linkedin": "https://linkedin.com/in/jamesmoran", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["Developer-led team", "Small team building data products", "Needs AI to scale content production"],
        "source_urls": ["https://growthlist.co/blog"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-004",
        "company_name": "Vessel",
        "domain": "vessel.land",
        "industry": "CRM Integration / Unified API",
        "geo": "US",
        "headcount": "11-50",
        "funding_stage": "Seed",
        "funding_amount": "$5.5M",
        "funding_date": "2025-02",
        "score": 81,
        "status": "new",
        "description": "Vessel is a unified CRM API that lets developers connect to Salesforce, HubSpot, and others via a single integration.",
        "linkedin_url": "https://linkedin.com/company/vessel-crm",
        "tech_stack": ["TypeScript", "Node.js", "React"],
        "hiring_signals": ["Building Sales Org", "Hiring Developers"],
        "contacts": [{"name": "Mark Ma", "title": "Co-Founder & CEO", "linkedin": "https://linkedin.com/in/markma", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["API-first company", "Seed stage with budget to spend", "Developer product = understands technical value"],
        "source_urls": ["https://vessel.land/blog"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-005",
        "company_name": "Dopt",
        "domain": "dopt.com",
        "industry": "Product Onboarding / User Flows",
        "geo": "US",
        "headcount": "11-50",
        "funding_stage": "Seed",
        "funding_amount": "$14M",
        "funding_date": "2024-11",
        "score": 78,
        "status": "new",
        "description": "Dopt helps product teams build in-app onboarding flows without engineering. Backed by a16z.",
        "linkedin_url": "https://linkedin.com/company/dopt",
        "tech_stack": ["React", "TypeScript", "Node.js"],
        "hiring_signals": ["Hiring ML Engineer", "Hiring Growth PM"],
        "contacts": [{"name": "Nick Nisi", "title": "CTO", "linkedin": "https://linkedin.com/in/nicknisi", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["$14M a16z backed", "No-code product = understands builder value", "Adding AI features to their platform"],
        "source_urls": ["https://dopt.com/blog"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-006",
        "company_name": "Formbricks",
        "domain": "formbricks.com",
        "industry": "Open Source / User Research",
        "geo": "Germany",
        "headcount": "11-50",
        "funding_stage": "Seed",
        "funding_amount": "$2.2M",
        "funding_date": "2025-01",
        "score": 74,
        "status": "new",
        "description": "Formbricks is an open-source survey and user research platform for product teams. Growing fast.",
        "linkedin_url": "https://linkedin.com/company/formbricks",
        "tech_stack": ["Next.js", "TypeScript", "Prisma", "PostgreSQL"],
        "hiring_signals": ["Hiring Full Stack Engineers", "Hiring AI Engineer"],
        "contacts": [{"name": "Johannes Dancker", "title": "CEO", "linkedin": "https://linkedin.com/in/johannesdancker", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["Open source team values speed", "Adding AI analysis to survey data", "European startup scaling quickly"],
        "source_urls": ["https://formbricks.com/blog"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-007",
        "company_name": "Attio",
        "domain": "attio.com",
        "industry": "CRM / Sales Intelligence",
        "geo": "UK",
        "headcount": "51-200",
        "funding_stage": "Series_A",
        "funding_amount": "$23.5M",
        "funding_date": "2024-09",
        "score": 71,
        "status": "new",
        "description": "Attio is a next-gen CRM built for modern GTM teams. Raised $23.5M Series A.",
        "linkedin_url": "https://linkedin.com/company/attio",
        "tech_stack": ["Elixir", "TypeScript", "React"],
        "hiring_signals": ["Hiring AI Engineers", "Building Sales Org"],
        "contacts": [{"name": "Nicolas Sharp", "title": "CEO", "linkedin": "https://linkedin.com/in/nicholassharp", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["$23M Series A", "Building AI features in CRM", "Competes with Salesforce = understands platform value"],
        "source_urls": ["https://attio.com/blog"],
        "discovered_at": _NOW,
    },
    {
        "id": "demo-lead-008",
        "company_name": "Calcom",
        "domain": "cal.com",
        "industry": "Open Source / Scheduling",
        "geo": "US",
        "headcount": "51-200",
        "funding_stage": "Series_A",
        "funding_amount": "$32M",
        "funding_date": "2024-08",
        "score": 68,
        "status": "new",
        "description": "Cal.com is the open-source Calendly alternative. $32M Series A, 25k+ GitHub stars.",
        "linkedin_url": "https://linkedin.com/company/calcom",
        "tech_stack": ["Next.js", "TypeScript", "Prisma", "tRPC"],
        "hiring_signals": ["Hiring AI Product Manager", "Hiring ML Engineer"],
        "contacts": [{"name": "Peer Richelsen", "title": "Co-Founder", "linkedin": "https://linkedin.com/in/peerrichelsen", "email": "", "seniority": "C-Suite"}],
        "score_reasons": ["$32M Series A", "Open source = developer-led", "Adding AI scheduling intelligence"],
        "source_urls": ["https://cal.com/blog"],
        "discovered_at": _NOW,
    },
]

DEMO_EMAILS = {
    "demo-lead-001": [
        {
            "id": "demo-email-001-1",
            "lead_id": "demo-lead-001",
            "sequence_step": 1,
            "delay_days": 0,
            "subject": "Re: AI agent infra for Landbase's GTM",
            "body": """Just read about Landbase's $1M seed round — congrats on the AI automation angle.

Saw you're hiring ML engineers to build out your agent workflows. Most early-stage AI teams hit the same wall at your stage: you need to ship features fast, but complex AI pipelines eat up weeks of engineering time.

At Natively AI, we've helped similar seed-stage AI companies go from idea → deployed agent in days, not months. Our visual builder lets you wire up LLMs, data sources, and custom logic without infrastructure overhead.

Given you're building AI-native sales automation, curious if you've considered how much faster you could iterate with a purpose-built AI development platform?

Worth a 15-min call this week?""",
            "linkedin_dm": "Hey Oliver — saw Landbase raised $1M for AI sales automation. We help teams like yours ship AI agents faster. Would love to show you how Natively AI could 10x your iteration speed. Worth a quick chat?",
            "status": "draft",
            "generated_at": _NOW,
        },
        {
            "id": "demo-email-001-2",
            "lead_id": "demo-lead-001",
            "sequence_step": 2,
            "delay_days": 3,
            "subject": "Following up — Landbase + Natively AI",
            "body": """Following up on my note about AI development speed.

Quick question: how long does it currently take your team to ship a new AI agent workflow end-to-end?

Most teams we work with say 3-4 weeks. With Natively AI, they're typically at 2-3 days.

Happy to walk you through a quick demo — I can show specifically how it would apply to outbound AI agents like what Landbase is building.""",
            "linkedin_dm": "Oliver — still think there's a fit here. 5 mins to see how Natively AI compares to what you're building in-house?",
            "status": "draft",
            "generated_at": _NOW,
        },
        {
            "id": "demo-email-001-3",
            "lead_id": "demo-lead-001",
            "sequence_step": 3,
            "delay_days": 7,
            "subject": "One thing that might be relevant for Landbase",
            "body": """Last note — promise.

Noticed Landbase is building AI agents for sales outreach, which is exactly what our platform was designed for. We have a template library of outbound agent flows that would cut your development time significantly.

If you're not the right person to evaluate this, who should I be talking to on your team?

Either way, I'd love to stay in touch as you scale.""",
            "linkedin_dm": "Oliver, is there someone on your eng team who evaluates AI dev tools? Happy to connect with them directly.",
            "status": "draft",
            "generated_at": _NOW,
        },
        {
            "id": "demo-email-001-4",
            "lead_id": "demo-lead-001",
            "sequence_step": 4,
            "delay_days": 14,
            "subject": "Closing the loop on Natively AI",
            "body": """Closing the loop since I haven't heard back — no worries at all.

Leaving this here in case timing changes: Natively AI helps AI-first teams like Landbase ship agents and workflows 10x faster without custom infra.

If you ever hit a dev bottleneck or want to evaluate alternatives to building in-house, I'm here.

Best of luck with the product — genuinely exciting what you're building.""",
            "linkedin_dm": "Closing the loop Oliver — best of luck with Landbase. Feel free to reach out whenever AI agent infra becomes a priority.",
            "status": "draft",
            "generated_at": _NOW,
        },
    ],
    "demo-lead-002": [
        {
            "id": "demo-email-002-1",
            "lead_id": "demo-lead-002",
            "sequence_step": 1,
            "delay_days": 0,
            "subject": "Re: Rho's AI push post-Series A",
            "body": """Saw Rho raised $8.2M Series A and you're expanding the AI capabilities of the platform.

Noticed you're hiring ML engineers — which usually means one of two things: either you're building AI features in-house from scratch, or you're evaluating tools to accelerate that.

At Natively AI, we work with fintech companies at your stage who need to ship AI-powered features fast without building the entire pipeline themselves. Our platform lets product teams wire up AI workflows visually — think automated financial insights, anomaly detection, smart categorization.

Would it make sense to see how other Series A fintechs are using Natively AI to ship AI features 3-4x faster?""",
            "linkedin_dm": "Hey Alex — congrats on Rho's Series A! Saw you're building AI features. We help fintech teams ship AI workflows faster. Quick demo?",
            "status": "draft",
            "generated_at": _NOW,
        },
    ],
    "demo-lead-003": [
        {
            "id": "demo-email-003-1",
            "lead_id": "demo-lead-003",
            "sequence_step": 1,
            "delay_days": 0,
            "subject": "Re: your data + AI analytics workflow",
            "body": """Just read your recent post on B2B data enrichment — the section on enterprise readiness hit home.

Saw you're hiring for data/analytics and process automation roles. Most data-driven startups at your stage face the same challenge: they need enterprise-grade AI capabilities but can't wait 3 months for dev cycles.

At Natively AI, we've helped similar B2B SaaS companies bridge that gap by turning AI ideas into deployed workflows without a dedicated ML team. One customer reduced their AI feature delivery time by 80% while tripling data throughput.

Given Growthlist's recent raise and your focus on scaling data capabilities, curious if you're open to seeing how other funded startups are automating their data workflows in days, not months?

Worth a 15-minute conversation?""",
            "linkedin_dm": "James — love what you're building at Growthlist. We help similar data companies ship AI workflows faster. Would love to show you Natively AI — quick chat?",
            "status": "draft",
            "generated_at": _NOW,
        },
    ],
}

DEMO_SIGNALS = [
    {
        "id": "demo-sig-001",
        "intent_type": "active_evaluation",
        "source": "G2",
        "source_url": "https://g2.com/products/replit/reviews",
        "quote": "We've been evaluating alternatives to Replit — their pricing is unpredictable and we need better enterprise controls for our AI agents.",
        "company_mentioned": "Replit",
        "lead_match": "demo-lead-001",
        "confidence": 94,
        "detected_at": _NOW,
    },
    {
        "id": "demo-sig-002",
        "intent_type": "switching_intent",
        "source": "Reddit",
        "source_url": "https://reddit.com/r/startups",
        "quote": "Anyone else frustrated with how long it takes to ship new AI features? Our team spends more time on infra than the actual product logic.",
        "company_mentioned": "General AI development pain",
        "lead_match": "demo-lead-002",
        "confidence": 87,
        "detected_at": _NOW,
    },
    {
        "id": "demo-sig-003",
        "intent_type": "budget_available",
        "source": "TechCrunch",
        "source_url": "https://techcrunch.com/rho-series-a",
        "quote": "Rho announced $8.2M Series A to accelerate its AI-powered spend management platform. The company plans to triple engineering headcount.",
        "company_mentioned": "Rho",
        "lead_match": "demo-lead-002",
        "confidence": 98,
        "detected_at": _NOW,
    },
    {
        "id": "demo-sig-004",
        "intent_type": "pain_point",
        "source": "Hacker News",
        "source_url": "https://news.ycombinator.com/item?id=123456",
        "quote": "The problem with building AI apps in 2025: you spend 80% of your time on orchestration and only 20% on the actual business logic. There has to be a better way.",
        "company_mentioned": "AI development tooling",
        "lead_match": "demo-lead-003",
        "confidence": 82,
        "detected_at": _NOW,
    },
    {
        "id": "demo-sig-005",
        "intent_type": "active_evaluation",
        "source": "G2",
        "source_url": "https://g2.com/products/builder-io/reviews",
        "quote": "Builder.io is great for marketing but we need something purpose-built for AI agent workflows. Looking for alternatives.",
        "company_mentioned": "Builder.io",
        "lead_match": "demo-lead-004",
        "confidence": 89,
        "detected_at": _NOW,
    },
]
