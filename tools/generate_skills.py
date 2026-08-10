#!/usr/bin/env python3
"""Generate the Zinc checkout skills from one template.

The retailer catalog is driven by the live public `GET https://api.zinc.com/retailers`
endpoint — the single source of truth — so the skills stay in sync automatically.
Everything retailer-specific that matters (name, domain, free-shipping terms)
comes from there; the only things not in the endpoint are an example product URL
(derived from the domain) and which retailers have /products/search (one
constant). Retailer-specific order constraints are NOT hardcoded — the order API
reports them at request time. Adding a retailer needs no code change.

`universal-checkout` is generated from this same template (a `universal` config),
so the shared sections — crucially the Auth/MPP/payment mechanics — can never
drift between the universal skill and the per-retailer skills.

Usage:

    python3 tools/generate_skills.py            # generate from the committed snapshot
    python3 tools/generate_skills.py --refresh  # re-fetch /retailers, update snapshot, generate

`--refresh` writes tools/retailers.json (committed) so builds are reproducible
and catalog changes show up as a reviewable diff.

Each skill is a self-contained folder (SKILL.md + references/errors.md),
installable via `npx skills add zincio/skills --skill <name>`.
Scope: US retailers, full lifecycle (discover -> buy -> track -> return).
"""

import json
import os
import shutil
import sys
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
SHARED_ERRORS = os.path.join(REPO_ROOT, "references", "errors.md")
SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retailers.json")
RETAILERS_URL = "https://api.zinc.com/retailers"

# Internal / non-consumer catalog entries we don't publish a checkout skill for.
EXCLUDE = {"zinc"}

# Retailers where GET /products/search + /products/{id}/offers apply.
PRODUCTS_API_RETAILERS = {"amazon", "walmart"}


def load_catalog(refresh):
    """Return the /retailers list, from the live endpoint (--refresh) or snapshot."""
    if refresh:
        with urllib.request.urlopen(RETAILERS_URL, timeout=30) as resp:
            data = json.load(resp)
        with open(SNAPSHOT, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"Refreshed snapshot from {RETAILERS_URL}")
    else:
        if not os.path.exists(SNAPSHOT):
            sys.exit("No tools/retailers.json snapshot — run with --refresh first.")
        with open(SNAPSHOT) as f:
            data = json.load(f)
    return data.get("retailers", data) if isinstance(data, dict) else data


def is_supported(raw):
    # New flat shape uses `supported`; pre-#622 shape used `is_supported`.
    return raw.get("supported", raw.get("is_supported", False))


def free_shipping_terms(raw):
    """Return (free_shipping, threshold_cents) handling both catalog shapes."""
    if "free_shipping" in raw:  # flat #622 shape
        return raw.get("free_shipping"), raw.get("free_shipping_threshold_cents")
    storefronts = raw.get("storefronts") or []
    us = next((s for s in storefronts if s.get("country") == "US"), None)
    sf = us or (storefronts[0] if storefronts else {})
    return sf.get("free_shipping"), sf.get("free_shipping_threshold_cents")


def build_retailers(catalog):
    """Turn the live catalog into render configs. No per-retailer overlay."""
    configs = []
    for raw in catalog:
        slug = raw.get("retailer")
        if not slug or slug in EXCLUDE or not is_supported(raw):
            continue
        domain = raw.get("base_url") or slug
        fs, threshold = free_shipping_terms(raw)
        configs.append({
            "slug": slug,
            "display": raw.get("display_name") or slug,
            "domain": domain,
            "example_url": f"https://www.{domain}/<product-page>",
            "psearch": slug in PRODUCTS_API_RETAILERS,
            "free_shipping": fs,  # None when the catalog doesn't expose it
            "ship_threshold_cents": threshold,
            "is_universal": False,
        })
    return configs


# The `universal` config renders skills/universal-checkout/ from this same
# template. A real example URL (Amazon) shows the request schema.
UNIVERSAL = {
    "slug": "universal",
    "display": "Zinc Universal Checkout",
    "domain": "zinc.com",
    "example_url": "https://www.amazon.com/dp/B09V3KXJPB",
    "psearch": True,  # universal covers the products API (Amazon & Walmart)
    "free_shipping": None,
    "ship_threshold_cents": None,
    "is_universal": True,
}

# --- Template --------------------------------------------------------------
# Retailer-specific phrasing is injected via the tokens computed in
# `variant_tokens()` so the ONE body below serves both the per-retailer skills
# and universal-checkout. The shared sections (Auth/MPP, order mechanics,
# tracking, returns, errors, safety) are literal here and identical everywhere.

FRONTMATTER = """---
name: {{NAME}}
description: {{DESCRIPTION}}
---
"""

BODY = """
# {{TITLE}}

{{INTRO}}

{{POWERED_NOTE}}

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **MPP — no account needed** → Use the `/agent/*` endpoints and pay per request with a **Stripe card** (via Stripe Link — no crypto), **Tempo** stablecoins, or **x402** (USDC on Base). `POST /agent/orders` to buy; `/agent/search` to discover ($0.01 per data call). `GET /retailers` is free.
- **Neither is set** → Ask the user to either sign up at [app.zinc.com](https://app.zinc.com) for an API key, or set up an MPP payment method. Try it without code at [agent.zinc.com](https://agent.zinc.com).

All amounts are in **US cents** (e.g. `5000` = $50.00).

## Authentication

### API Key Auth

```
Authorization: Bearer $ZINC_API_KEY
```

### MPP Auth (Machine Payments Protocol)

MPP is an open standard for HTTP 402 machine-to-machine payments (spec: [mpp.dev](https://mpp.dev)) — no API key needed upfront:

1. Send the request (e.g. `POST /agent/orders`) with **no** `Authorization` header → HTTP `402 Payment Required`. The challenge advertises every available rail: MPP methods as one `WWW-Authenticate: Payment …` header each (`method="stripe"`, `method="tempo"`), and **x402** as a `PAYMENT-REQUIRED` header (USDC on Base).
2. Pick the rail your client supports and pay, then retry: MPP methods resubmit with `Authorization: Payment <credential>`; x402 clients resubmit with a `PAYMENT-SIGNATURE` header. Client libraries handle this loop automatically.
3. For orders, save the `X-Api-Key` response header — a Bearer token scoped to that order, for `GET /orders/{id}`.

**Select a single rail with `?method=`.** A 402 can carry several challenges at once, and many HTTP clients mishandle repeated `WWW-Authenticate` headers (they fold them into one comma-joined value, corrupting the params). If your client only supports one rail, append **`?method=stripe`**, `?method=tempo`, or `?method=x402` to `/agent/orders` to get a single, unambiguous challenge. Omit it to advertise all rails (for discovery). If you do parse multiple challenges yourself, read the **raw** header list (in Python `httpx`, `resp.headers.raw`) and select by `method=`.

**Payment methods:**

| Method | Pay with | How |
|--------|----------|-----|
| **Stripe** (card) | any credit/debit card via **Stripe Link** — no crypto wallet | mint a one-time Shared Payment Token with the [`create-payment-credential`](https://skills.sh/stripe/link-cli) skill (`link-cli`), then pay `/agent/orders?method=stripe`. |
| **Tempo** | USDC stablecoin, on-chain | `pip install pympp` (Python) / `npm install mppx viem` (TS) — the client signs and pays. |
| **x402** | USDC on **Base** (`eip155:8453`) | advertised via the `PAYMENT-REQUIRED` header on `/agent/orders`; pay with any x402 client (e.g. AgentCash). *x402 is offered on orders, not the $0.01 data endpoints.* |

## Find a product (optional)

{{FIND_INTRO}}

```bash
curl "https://api.zinc.com/search?q=cast+iron+skillet" \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

{{FIND_FILTER}}

Paying via MPP (no account)? Use the metered `POST /agent/search` instead — $0.01 per call, returns a `Payment-Receipt` header; the MPP client handles the 402 → pay → retry automatically. `GET /retailers` is free.{{PRODUCT_SEARCH}}

## Place an order — `POST /orders` (or `POST /agent/orders` for MPP)

**Required fields:**

- `products` — array of product objects (see below)
- `shipping_address` — US delivery address
- `max_price` — integer, the **maximum total in cents** Zinc may spend before finalizing (your price ceiling)

**Product object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✓ | {{URL_DESC}} |
| `quantity` | integer 1–100 | — | Units to buy (default 1) |
| `variant` | array of `{ label, value }` | — | Options, e.g. `[{ "label": "Size", "value": "Large" }]` |
| `condition_in` | array | — | Allowlist of acceptable conditions |
| `condition_not_in` | array | — | Denylist of excluded conditions |

**Condition enum:** `New`, `Refurbished`, `UsedLikeNew`, `UsedVeryGood`, `UsedGood`, `UsedAcceptable`.

**Shipping address:** `first_name`, `last_name`, `address_line1`, `address_line2` (optional), `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (defaults to `US`).

**Optional order fields:** `handling_days_max` (integer ≥1 — cap on seller handling time, the lever for bounding how fast it ships), `is_gift` (boolean — suppress prices on the packing slip), `idempotency_key` (string ≤36 chars), `metadata` (object), `po_number` (string).

### Controlling price & shipping

There is no shipping-*method* picker; control cost and speed with: `max_price` (price ceiling), `condition_in` (allow used/refurbished for a cheaper qualifying offer), and `handling_days_max` (cap handling time). `max_price` is the **total** ceiling — item + shipping + tax — so leave room for shipping (see `GET /retailers` for each retailer's free-shipping terms).

**Order statuses:** `pending` → `in_progress` → `order_placed` | `order_failed` | `cancelled` | `cancelled_by_retailer`.

**Example (API key):**

```bash
curl -X POST https://api.zinc.com/orders \\
  -H "Authorization: Bearer $ZINC_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "products": [{ "url": "{{EXAMPLE_URL}}", "quantity": 1, "condition_in": ["New"] }],
    "max_price": 5000,
    "handling_days_max": 5,
    "shipping_address": {
      "first_name": "Jane",
      "last_name": "Doe",
      "address_line1": "123 Main St",
      "city": "San Francisco",
      "state": "CA",
      "postal_code": "94105",
      "phone_number": "5551234567",
      "country": "US"
    }
  }'
```

### Paying via MPP — `POST /agent/orders`

Same request body, no API key — pay inline. Agent authorizes `max_price + $1.00` upfront (the `$1` is the Zinc API fee, so the full `max_price` stays available to the retailer). **Validation runs before payment:** an invalid URL/retailer/address returns HTTP 400 with no charge, and the credential stays reusable. On success: charged `actual_total + $1`, with any difference under `max_price` auto-refunded; on failure: full refund (server-side). The HTTP 201 response includes `X-Api-Key` (a `zn_live_...` Bearer token, scoped to this order) and `Payment-Receipt`.

- **Stripe card (recommended for a human with just a card):** use the [`create-payment-credential`](https://skills.sh/stripe/link-cli) skill to mint a Shared Payment Token, then have that skill pay `https://api.zinc.com/agent/orders?method=stripe`.
- **Tempo (stablecoin):** `npx mppx https://api.zinc.com/agent/orders --method POST --body '…'`, or `pympp`/`mppx` in code — the client handles the 402 → pay → retry.
- **x402 (USDC on Base):** any x402 client (e.g. AgentCash) pays `POST /agent/orders` directly off the `PAYMENT-REQUIRED` header.

```python
# Tempo example — pip install pympp
from mpp.client import Client
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent, CHAIN_ID

account = TempoAccount.from_key("0x<your-private-key>")
method = tempo(chain_id=CHAIN_ID, account=account, intents={"charge": ChargeIntent()})

async with Client(methods=[method]) as client:
    response = await client.post(
        "https://api.zinc.com/agent/orders?method=tempo",
        json={
            "products": [{"url": "{{EXAMPLE_URL}}", "quantity": 1}],
            "max_price": 5000,
            "shipping_address": {
                "first_name": "Jane", "last_name": "Doe",
                "address_line1": "123 Main St", "city": "San Francisco",
                "state": "CA", "postal_code": "94105",
                "phone_number": "5551234567", "country": "US",
            },
        },
    )
    # Client handles the 402 → pay → retry flow automatically
    order = response.json()
    api_key = response.headers["X-Api-Key"]  # use for GET /orders/{id}
```

## Track & manage orders

### Get order — `GET /orders/{id}`

Retrieve a single order by UUID (Bearer token: `ZINC_API_KEY` or the MPP `X-Api-Key`). The response includes `status`, `items`, `shipping_address`, plus:

- `tracking_numbers` — array of `{ id, carrier, tracking_number, status, checkpoints, created_at }`. `status` (always present) is the carrier-derived shipment state: `pending` | `in_transit` | `delivered`. `checkpoints` is the per-scan timeline (most recent first). Added automatically; there is no separate tracking endpoint.
- `job_result` (once terminal) — `success`, `error`, `error_type`, `estimated_delivery`, `merchant_order_ids`, and `price_components` (`subtotal`, `tax`, `shipping`, `total`, `currency`).

```bash
curl https://api.zinc.com/orders/<order_id> \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### List orders — `GET /orders`

Returns `{ orders: [...] }`. Requires Bearer token auth. Add `?include=tracking_events` to also get the full `checkpoints` timeline.

### Cancel order — `POST /orders/{id}/cancel`

Cancels an order **only while `pending`** (still queued); once `in_progress` or done it can't be cancelled. Returns `204 No Content` on success.

## Returns — `POST /returns`

Open a return against a placed order (Bearer token auth).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `order_id` | UUID | ✓ | The order being returned |
| `items` | array of `{ order_item_id, quantity }` | ✓ | Items to return (`order_item_id` comes from the order's `items`) |
| `reason` | enum | ✓ | `damaged`, `not_delivered`, `empty_box`, `wrong_item`, `defective`, `not_as_described`, `wrong_size`, `no_longer_needed`, `forced_cancellation`, `other` |
| `notes` | string ≤2000 | — | Free-text detail |

**Response (201):** `{ id, order_id, status, reason, items, label_urls, merchant_return_id, ... }`. Return `status`: `open` → `approved` | `denied` | `credited`. Ship via the URLs in `label_urls`. Also `GET /returns` and `GET /returns/{id}`.

```bash
curl -X POST https://api.zinc.com/returns \\
  -H "Authorization: Bearer $ZINC_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "order_id": "8c2d...",
    "items": [{ "order_item_id": "a1b2...", "quantity": 1 }],
    "reason": "damaged",
    "notes": "Arrived with a crushed corner."
  }'
```

## Error Handling

See [references/errors.md](https://github.com/zincio/skills/blob/master/skills/{{SLUG}}-checkout/references/errors.md) for the full error code reference.

Key points:

- HTTP errors return `{ error: { code, message, details } }`
- Order processing failures appear in the order's `job_result.error_type` field
- Common issues: `max_price_exceeded`, `product_out_of_stock`, `invalid_shipping_address`
- MPP payment failures return HTTP 402 with `{ error: { code: "payment_failed", details: { reason: "..." } } }`
- HTTP 402 without `payment_failed` code means the server is issuing a payment challenge (normal MPP flow — the client handles this automatically)

## Order Status Tracking

Orders process asynchronously and typically take **5–10 minutes**. After placing an order:

1. Wait ~7 minutes, then poll `GET /orders/{id}`.
2. If still `pending` or `in_progress`, poll again in 3–5 minutes.
3. Stop polling when the status is terminal.

**Terminal statuses:** `order_placed`, `order_failed`, `cancelled`, `cancelled_by_retailer`
**Non-terminal:** `pending`, `in_progress`

If your platform supports scheduled tasks or cron jobs, schedule a check ~7 minutes after order creation rather than polling in a loop.

## Safety

- **Always confirm with the user** before placing an order (`POST /orders` or `POST /agent/orders`) or opening a return. Orders spend real money.
- Reading operations (search, `GET /orders`, `GET /orders/{id}`, `GET /returns`) are always safe.
- Set `max_price` to cover the **full** cost — item price **+ tax + shipping/handling** — not just the item. It's the total ceiling Zinc won't exceed, so too-low a value trips `max_price_exceeded`.
- MPP orders authorize `max_price + $1` on the agent's payment method (Stripe card, Tempo wallet, or x402/USDC) — ensure sufficient balance/credit before placing.

{{NOTES_SECTION}}## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
"""

RETAILER_PRODUCT_SEARCH = """

{{DISPLAY}} is one of the few retailers with richer product data (currently Amazon & Walmart only). For best-price comparison, use `GET /products/search?query=<term>&retailer={{SLUG}}` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer={{SLUG}}` to compare offers by **price and condition** before ordering. On the MPP rail these are `POST /agent/products/search`, `POST /agent/products/offers`, and `POST /agent/products/details` (query param `product_id=…&retailer={{SLUG}}`), $0.01 per call."""

UNIVERSAL_PRODUCT_SEARCH = """

**Richer product data (Amazon & Walmart only).** For best-price comparison on those two, use `GET /products/search?query=<term>&retailer=amazon|walmart` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer=amazon|walmart` to compare offers by **price and condition** before ordering. On the MPP rail these are `POST /agent/products/search`, `POST /agent/products/offers`, and `POST /agent/products/details`, $0.01 per call."""

RETAILER_DESCRIPTION = (
    "Buy products from {{DISPLAY}} ({{DOMAIN}}) and manage those orders via the Zinc "
    "API (zinc.com). Use when the user wants to purchase, order, or check out an item "
    "from {{DISPLAY}}, check {{DISPLAY}} order status or tracking, cancel a {{DISPLAY}} "
    "order, or return a {{DISPLAY}} item. One API also covers Amazon, Walmart, Target, "
    "Best Buy and 50+ other US retailers. Supports API key auth (ZINC_API_KEY) or "
    "Machine Payments Protocol (MPP) for per-request payments via a Stripe card, Tempo "
    "stablecoins, or x402 (USDC on Base)."
)

UNIVERSAL_DESCRIPTION = (
    "Discover, buy, track, and return products across Amazon, Walmart, Target, Best Buy, "
    "eBay, and 50+ other US retailers via the Zinc API (zinc.com). Use when the user wants "
    "to search for or buy a product, check out, check order status or tracking, cancel an "
    "order, or return an item programmatically. Supports API key auth (ZINC_API_KEY) or "
    "Machine Payments Protocol (MPP) for per-request payments via a Stripe card (Stripe "
    "Link), Tempo stablecoins, or x402 (USDC on Base)."
)

RETAILER_POWERED_NOTE = (
    "> **Powered by Zinc Universal Checkout.** The same API buys from {{DISPLAY}} and 50+ "
    "other US retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order "
    "across multiple retailers from one skill, install the "
    "[`universal-checkout`](https://github.com/zincio/skills/tree/master/skills/universal-checkout) "
    "skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: "
    "`GET https://api.zinc.com/retailers`."
)

UNIVERSAL_POWERED_NOTE = (
    "> Live supported-retailer list: `GET https://api.zinc.com/retailers` (free, no auth). "
    "If an agent only ever buys from one store, there are also per-retailer skills "
    "(`amazon-checkout`, `walmart-checkout`, …) — see the repo README."
)

RETAILER_FIND_INTRO = (
    "If the user already has a {{DISPLAY}} product URL, skip to **Place an order**. "
    "Otherwise search for one:"
)
UNIVERSAL_FIND_INTRO = (
    "If the user gives you a product URL, skip to **Place an order**. Otherwise find an "
    "orderable product first:"
)

RETAILER_FIND_FILTER = (
    "`GET /search` returns `{ status, query, results: [...] }` across retailers; each "
    "result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), "
    "`stars`. Filter results to `retailer == \"{{SLUG}}\"` for {{DISPLAY}}-only, then pass "
    "the `url` into an order."
)
UNIVERSAL_FIND_FILTER = (
    "`GET /search` returns `{ status, query, results: [...] }` across retailers; each "
    "result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), "
    "`stars`, `available`. Pass a result's `url` straight into an order."
)


def _dollars(cents):
    """cents -> '$45' for whole dollars, '$45.99' when there are cents."""
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def shipping_note(r):
    """Free-shipping line, from /retailers fields. Empty when not exposed."""
    fs = r.get("free_shipping")
    th = r.get("ship_threshold_cents")
    if fs is None:
        return ""
    if fs is False:
        return ("**Shipping:** {{DISPLAY}} has no flat free-shipping threshold — "
                "shipping is added per order, so leave room for it in `max_price`.")
    if th == 0:
        return "**Shipping:** {{DISPLAY}} ships free on all orders."
    if th is None:
        return ("**Shipping:** {{DISPLAY}} offers free shipping on qualifying orders; "
                "below the threshold shipping is added — leave room in `max_price`.")
    return (f"**Shipping:** {{{{DISPLAY}}}} ships free on orders over {_dollars(th)}; "
            "below that, shipping is added to the total — leave room in `max_price`.")


def notes_section(r):
    """The optional '## Retailer notes' block — only when /retailers gives us
    something real to say. Universal has no single-retailer shipping terms."""
    if r.get("is_universal"):
        return ""
    sn = shipping_note(r)
    if not sn:
        return ""
    return "## Retailer notes\n\n" + sn + "\n\n"


def variant_tokens(r):
    """Retailer-specific vs universal phrasing for the shared body."""
    if r.get("is_universal"):
        return {
            "NAME": "universal-checkout",
            "DESCRIPTION": UNIVERSAL_DESCRIPTION,
            "TITLE": "Universal Checkout",
            "INTRO": (
                "Discover, buy, track, and return products across US online retailers "
                "through the Zinc API (`https://api.zinc.com`). One API covers Amazon, "
                "Walmart, Target, Best Buy, eBay, Home Depot, Lowe's, Wayfair, and 50+ more."
            ),
            "POWERED_NOTE": UNIVERSAL_POWERED_NOTE,
            "FIND_INTRO": UNIVERSAL_FIND_INTRO,
            "FIND_FILTER": UNIVERSAL_FIND_FILTER,
            "URL_DESC": "Direct product page URL on a supported retailer",
            "PRODUCT_SEARCH": UNIVERSAL_PRODUCT_SEARCH,
        }
    return {
        "NAME": f"{r['slug']}-checkout",
        "DESCRIPTION": RETAILER_DESCRIPTION,
        "TITLE": "{{DISPLAY}} Checkout",
        "INTRO": (
            "Buy, track, and return products from {{DISPLAY}} ({{DOMAIN}}) through the "
            "Zinc API (`https://api.zinc.com`). US orders."
        ),
        "POWERED_NOTE": RETAILER_POWERED_NOTE,
        "FIND_INTRO": RETAILER_FIND_INTRO,
        "FIND_FILTER": RETAILER_FIND_FILTER,
        "URL_DESC": "Direct {{DISPLAY}} product page URL (on {{DOMAIN}})",
        "PRODUCT_SEARCH": RETAILER_PRODUCT_SEARCH if r["psearch"] else "",
    }


def render(r):
    tok = variant_tokens(r)
    out = FRONTMATTER + BODY
    # Inject variant sections first (they contain {{DISPLAY}}/{{SLUG}} tokens
    # that the final pass resolves).
    for key, val in tok.items():
        out = out.replace("{{" + key + "}}", val)
    out = out.replace("{{NOTES_SECTION}}", notes_section(r))
    # Retailer tokens last so they reach injected blocks too.
    out = out.replace("{{DISPLAY}}", r["display"])
    out = out.replace("{{SLUG}}", r["slug"])
    out = out.replace("{{DOMAIN}}", r["domain"])
    out = out.replace("{{EXAMPLE_URL}}", r["example_url"])
    return out


README = os.path.join(REPO_ROOT, "README.md")
TABLE_START = "<!-- SKILLS-TABLE:START (generated by tools/generate_skills.py — do not edit by hand) -->"
TABLE_END = "<!-- SKILLS-TABLE:END -->"


def update_readme_table(retailers):
    """Rewrite the skills table in README.md between the markers."""
    rows = [
        "| Skill | Buys from | Install |",
        "|-------|-----------|---------|",
        "| [`universal-checkout`](skills/universal-checkout/SKILL.md) | **Universal** — all supported retailers | `npx skills add zincio/skills --skill universal-checkout` |",
    ]
    for r in retailers:
        s = r["slug"]
        rows.append(
            f"| [`{s}-checkout`](skills/{s}-checkout/SKILL.md) | {r['display']} | "
            f"`npx skills add zincio/skills --skill {s}-checkout` |"
        )
    block = TABLE_START + "\n" + "\n".join(rows) + "\n" + TABLE_END
    with open(README) as f:
        text = f.read()
    if text.count(TABLE_START) != 1 or text.count(TABLE_END) != 1:
        sys.exit(
            f"README.md must contain exactly one {TABLE_START!r} and one "
            f"{TABLE_END!r} (found {text.count(TABLE_START)} / {text.count(TABLE_END)})."
        )
    pre, _, rest = text.partition(TABLE_START)
    _, _, post = rest.partition(TABLE_END)
    with open(README, "w") as f:
        f.write(pre + block + post)


def write_skill(r):
    """Render one skill folder (SKILL.md + shared errors.md). Returns folder name."""
    folder_name = f"{r['slug']}-checkout"
    folder = os.path.join(SKILLS_DIR, folder_name)
    refs = os.path.join(folder, "references")
    os.makedirs(refs, exist_ok=True)
    with open(os.path.join(folder, "SKILL.md"), "w") as f:
        f.write(render(r))
    shutil.copyfile(SHARED_ERRORS, os.path.join(refs, "errors.md"))
    return folder_name


def main():
    refresh = "--refresh" in sys.argv[1:]
    catalog = load_catalog(refresh)
    retailers = build_retailers(catalog)

    # universal-checkout is generated from the same template as the retailers,
    # so the shared sections (esp. Auth/MPP) can never drift.
    written = [write_skill(UNIVERSAL)]
    for r in retailers:
        written.append(write_skill(r))

    # Prune stale generated skills: a retailer dropped or renamed in the catalog
    # leaves a `<slug>-checkout/` folder that would still be installable.
    keep = set(written)
    removed = []
    for entry in sorted(os.listdir(SKILLS_DIR)) if os.path.isdir(SKILLS_DIR) else []:
        path = os.path.join(SKILLS_DIR, entry)
        if os.path.isdir(path) and entry.endswith("-checkout") and entry not in keep:
            shutil.rmtree(path)
            removed.append(entry)

    update_readme_table(retailers)

    print(f"Generated {len(written)} skills from {len(catalog)} cataloged retailers:")
    for w in written:
        print(f"  skills/{w}/")
    if removed:
        print(f"Pruned {len(removed)} stale skill(s): {', '.join(removed)}")
    print("Updated README skills table.")


if __name__ == "__main__":
    main()
