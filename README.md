# Universal Checkout Skills

[Agent Skills](https://agentskills.io) for **buying products and managing orders** through the [Zinc API](https://zinc.com) — programmatic checkout across Amazon, Walmart, Target, Best Buy, eBay, and 50+ other retailers with a single API.

This repo ships **one universal skill** (every retailer, full order lifecycle) plus **per-retailer skills** for the retailers people search for by name. Install the universal one for general use; install a retailer-specific one when you only buy from a single store.

## Skills

| Skill | Buys from | Install |
|-------|-----------|---------|
| [`zinc-orders`](SKILL.md) | **Universal** — all supported retailers | `npx skills add zincio/universal-checkout-skill` |
| [`amazon-checkout`](skills/amazon-checkout/SKILL.md) | Amazon | `npx skills add zincio/universal-checkout-skill --skill amazon-checkout` |
| [`walmart-checkout`](skills/walmart-checkout/SKILL.md) | Walmart | `… --skill walmart-checkout` |
| [`target-checkout`](skills/target-checkout/SKILL.md) | Target | `… --skill target-checkout` |
| [`bestbuy-checkout`](skills/bestbuy-checkout/SKILL.md) | Best Buy | `… --skill bestbuy-checkout` |
| [`ebay-checkout`](skills/ebay-checkout/SKILL.md) | eBay | `… --skill ebay-checkout` |
| [`homedepot-checkout`](skills/homedepot-checkout/SKILL.md) | The Home Depot | `… --skill homedepot-checkout` |
| [`lowes-checkout`](skills/lowes-checkout/SKILL.md) | Lowe's | `… --skill lowes-checkout` |
| [`wayfair-checkout`](skills/wayfair-checkout/SKILL.md) | Wayfair | `… --skill wayfair-checkout` |
| [`1800flowers-checkout`](skills/1800flowers-checkout/SKILL.md) | 1-800-Flowers | `… --skill 1800flowers-checkout` |
| [`acehardware-checkout`](skills/acehardware-checkout/SKILL.md) | Ace Hardware | `… --skill acehardware-checkout` |
| [`pokemoncenter-checkout`](skills/pokemoncenter-checkout/SKILL.md) | Pokémon Center | `… --skill pokemoncenter-checkout` |

> **Which should I install?** The per-retailer skills are the same full lifecycle (order → track → manage) retargeted for one store — handy when an agent only ever buys from, say, Amazon, and for discovery. If you buy across multiple retailers, install the **universal** `zinc-orders` skill instead of stacking several near-identical retailer skills (overlapping descriptions can make skill triggering ambiguous).
>
> Live supported-retailer list: `GET https://api.zinc.com/retailers`.

## What these skills do

- **Place orders** — `POST /orders` (API key) or `POST /agent/orders` (Machine Payments Protocol — pay per-order with on-chain crypto, no account needed)
- **Track & list orders** — `GET /orders`, `GET /orders/{id}`
- **Managed accounts** — order with a user's own retailer credentials (membership/business pricing)
- **Error handling** — full code reference in each skill's `references/errors.md`

## Prerequisites

- **API Key auth:** A Zinc API key (sign up at [app.zinc.com](https://app.zinc.com)). Set `ZINC_API_KEY`.
- **MPP auth:** A funded Tempo wallet key. Set `TEMPO_PRIVATE_KEY`. No Zinc account needed — pay per-order with on-chain crypto.

## Installation

These are [Agent Skills](https://agentskills.io) — folders containing a `SKILL.md` with metadata and instructions that any compatible agent (Claude Code, Cursor, Gemini CLI, VS Code, GitHub Copilot, and [many others](https://agentskills.io/home)) can discover and use.

```bash
# Universal skill (recommended for most users)
npx skills add zincio/universal-checkout-skill

# A single retailer
npx skills add zincio/universal-checkout-skill --skill amazon-checkout
```

Or clone into your workspace `skills/` directory:

```bash
git clone https://github.com/zincio/universal-checkout-skill.git ./skills/universal-checkout-skill
```

Skills use progressive disclosure — at startup only `name` and `description` load; full instructions are read into context only when a matching task is detected.

### OpenClaw

[OpenClaw](https://docs.openclaw.ai) loads skills from the workspace (`<workspace>/skills/`), user (`~/.openclaw/skills/`), and bundled locations. Install via [ClawHub](https://clawhub.ai/a5huynh/universal-checkout):

```bash
clawhub install universal-checkout
```

OpenClaw hot-reloads skills when `SKILL.md` changes — no restart needed.

## Repo layout & maintenance

```
├── SKILL.md                       # universal skill (zinc-orders) — all retailers
├── references/errors.md           # shared error reference
├── skills/
│   └── <retailer>-checkout/       # per-retailer skill (self-contained)
│       ├── SKILL.md
│       └── references/errors.md
└── tools/generate_skills.py       # generates every skills/<retailer>-checkout/ folder
```

**The per-retailer skills are generated, not hand-edited.** To change them — or add a retailer — edit the template / `RETAILERS` config in [`tools/generate_skills.py`](tools/generate_skills.py) and re-run:

```bash
python3 tools/generate_skills.py
```

This keeps all retailers consistent and in sync with the live `/retailers` list from a single source.

## Documentation

- [SKILL.md](SKILL.md) — universal skill: endpoints, auth, examples, safety
- [references/errors.md](references/errors.md) — HTTP status codes, API error codes, order processing error types
- [Zinc API docs](https://www.zinc.com/docs) — full API reference

## Support

- Email: [support@zinc.com](mailto:support@zinc.com)
- Book a call with our CEO: [cal.com/zinc-ian/15min](https://cal.com/zinc-ian/15min)
- Discord: [discord.gg/cuXgfczYfj](https://discord.gg/cuXgfczYfj)
