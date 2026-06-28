#!/usr/bin/env python3
"""Generate per-retailer Zinc checkout skills from one template.

The retailer catalog is driven by the live public `GET https://api.zinc.com/retailers`
endpoint — the single source of truth — so the skills stay in sync automatically.
Everything retailer-specific that matters (name, domain, free-shipping terms)
comes from there; the only things not in the endpoint are an example product URL
(derived from the domain) and which retailers have /products/search (one
constant). Retailer-specific order constraints are NOT hardcoded — the order API
reports them at request time. Adding a retailer needs no code change.

Usage:

    python3 tools/generate_skills.py            # generate from the committed snapshot
    python3 tools/generate_skills.py --refresh  # re-fetch /retailers, update snapshot, generate

`--refresh` writes tools/retailers.json (committed) so builds are reproducible
and catalog changes show up as a reviewable diff.

Each retailer gets a self-contained skill folder (SKILL.md + references/errors.md),
installable standalone via `npx skills add zincio/skills --skill <retailer>-checkout`.
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

# --- The little the catalog can't tell us ----------------------------------
# /retailers is the source of truth for the catalog (which retailers exist,
# display_name, base_url, free-shipping terms). Only two things it doesn't carry
# are handled here, and neither is a per-retailer overlay:
#
#   * example product URL  -> derived from base_url. Agents get real URLs from
#     /search or the user; they never build them from patterns, so a placeholder
#     that shows the request *schema* is all an example needs.
#   * products-API coverage -> one capability constant (not 11 entries).
#
# Retailer-specific order constraints are deliberately NOT encoded here — the
# order API reports them at request time. So adding a retailer is ZERO code:
# once it's `supported` in /retailers, --refresh + regenerate produces a skill.

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
    """Return (free_shipping, threshold_cents) handling both catalog shapes.

    The #622 flat shape carries these at the top level. The current prod shape
    nests them per-country under `storefronts[]` — we're US-only, so read the US
    storefront (falling back to the first one). Returns (None, None) when the
    catalog doesn't expose free-shipping at all — we don't guess."""
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
        })
    return configs

# --- Template --------------------------------------------------------------
# Tokens: {{DISPLAY}} {{SLUG}} {{DOMAIN}} {{EXAMPLE_URL}}
# {{PRODUCT_SEARCH}} and {{RETAILER_NOTE}} are assembled in Python.

FRONTMATTER = """---
name: {{SLUG}}-checkout
description: Buy products from {{DISPLAY}} ({{DOMAIN}}) and manage those orders via the Zinc API (zinc.com). Use when the user wants to purchase, order, or check out an item from {{DISPLAY}}, check {{DISPLAY}} order status or tracking, cancel a {{DISPLAY}} order, or return a {{DISPLAY}} item. One API also covers Amazon, Walmart, Target, Best Buy and 50+ other US retailers. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for per-request payments via Stripe cards/wallets or Tempo stablecoins.
---
"""

BODY = """
# {{DISPLAY}} Checkout

Buy, track, and return products from {{DISPLAY}} ({{DOMAIN}}) through the Zinc API (`https://api.zinc.com`). US orders.

> **Powered by Zinc Universal Checkout.** The same API buys from {{DISPLAY}} and 50+ other US retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order across multiple retailers from one skill, install the [`universal-checkout`](https://github.com/zincio/skills/tree/main/skills/universal-checkout) skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: `GET https://api.zinc.com/retailers`.

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **MPP — no account needed** → Use the `/agent/*` endpoints; pay per request via **Tempo stablecoins** (`TEMPO_PRIVATE_KEY`, on-chain) or **Stripe** (cards/wallets via Stripe Link). `POST /agent/orders` to buy; `/agent/search` to discover ($0.01 per data call). `GET /retailers` is free.
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or set up an MPP payment method (Tempo wallet or Stripe). Try it without code at <https://agent.zinc.com>.

All amounts are in **US cents** (e.g. `5000` = $50.00).

## Authentication

### API Key Auth

```
Authorization: Bearer $ZINC_API_KEY
```

### MPP Auth (Machine Payments Protocol)

MPP is an open standard for HTTP 402 machine-to-machine payments (spec: <https://mpp.dev>) — no API key needed upfront:

1. Send the request (e.g. `POST /agent/orders`) with no `Authorization` header → receive HTTP `402 Payment Required` with one `WWW-Authenticate: Payment …` header per supported payment method
2. The MPP client picks a method, completes payment, and retries with `Authorization: Payment <credential>` → success
3. For orders, save the `X-Api-Key` response header — a Bearer token (scoped to that order) for `GET /orders/{id}`

**Payment methods** (the client auto-selects from the 402's `WWW-Authenticate` headers): **Stripe** (cards/wallets via Stripe Link / Shared Payment Tokens) or **Tempo** (stablecoins on-chain). Client libraries handle the flow automatically: Python `pip install pympp`, TypeScript `npm install mppx viem`, CLI `npx mppx`.

## Find a product (optional)

If the user already has a {{DISPLAY}} product URL, skip to **Place an order**. Otherwise search for one:

```bash
curl "https://api.zinc.com/search?q=cast+iron+skillet" \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

`GET /search` returns `{ status, query, results: [...] }` across retailers; each result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), `stars`. Filter results to `retailer == "{{SLUG}}"` for {{DISPLAY}}-only, then pass the `url` into an order.

Paying via MPP (Stripe or Tempo, no account)? Use the metered `GET /agent/search` instead — $0.01 per call, returns a `Payment-Receipt` header; the MPP client handles the 402 → pay → retry automatically. `GET /retailers` is free.{{PRODUCT_SEARCH}}

## Place an order — `POST /orders` (or `POST /agent/orders` for MPP)

**Required fields:**

- `products` — array of product objects (see below)
- `shipping_address` — US delivery address
- `max_price` — integer, the **maximum total in cents** Zinc may spend before finalizing (your price ceiling)

**Product object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✓ | Direct {{DISPLAY}} product page URL (on {{DOMAIN}}) |
| `quantity` | integer 1–100 | — | Units to buy (default 1) |
| `variant` | array of `{ label, value }` | — | Options, e.g. `[{ "label": "Size", "value": "Large" }]` |
| `condition_in` | array | — | Allowlist of acceptable conditions |
| `condition_not_in` | array | — | Denylist of excluded conditions |

**Condition enum:** `New`, `Refurbished`, `UsedLikeNew`, `UsedVeryGood`, `UsedGood`, `UsedAcceptable`.

**Shipping address:** `first_name`, `last_name`, `address_line1`, `address_line2` (optional), `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (defaults to `US`).

**Optional order fields:** `handling_days_max` (integer ≥1 — cap on seller handling time, the lever for bounding how fast it ships), `is_gift` (boolean — suppress prices on the packing slip), `idempotency_key` (string ≤36 chars), `metadata` (object), `po_number` (string).

### Controlling price & shipping

There is no shipping-*method* picker; control cost and speed with: `max_price` (price ceiling), `condition_in` (allow used/refurbished for a cheaper qualifying offer), and `handling_days_max` (cap handling time). `max_price` is the **total** ceiling — item + shipping + tax — so leave room for shipping (see `GET /retailers` for {{DISPLAY}}'s free-shipping terms).

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

Same request body, no API key — pay inline via Stripe or Tempo. Agent authorizes `max_price + $1.00` upfront (the `$1` is the Zinc API fee, so the full `max_price` stays available to the retailer). **Validation runs before payment:** an invalid URL/retailer/address returns HTTP 400 with no charge, and the credential stays reusable. On success: charged `actual_total + $1`, with any difference under `max_price` auto-refunded; on failure: full refund (server-side). The HTTP 201 response includes `X-Api-Key` (a `zn_live_...` Bearer token, scoped to this order) and `Payment-Receipt`. Quick test: `npx mppx https://api.zinc.com/agent/orders --method POST --body '…'`.

```python
# pip install pympp
from mpp.client import Client
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent, CHAIN_ID

account = TempoAccount.from_key("0x<your-private-key>")
method = tempo(chain_id=CHAIN_ID, account=account, intents={"charge": ChargeIntent()})

async with Client(methods=[method]) as client:
    response = await client.post(
        "https://api.zinc.com/agent/orders",
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

For testnet, import `TESTNET_CHAIN_ID` and pass it as `chain_id`. TypeScript is equivalent via `mppx`. To use Stripe directly (Shared Payment Tokens), see <https://docs.zinc.com/v2/mpp#using-stripe-with-mpp>.

## Track & manage orders

### Get order — `GET /orders/{id}`

Retrieve a single order by UUID (Bearer token: `ZINC_API_KEY` or the MPP `X-Api-Key`). The response includes `status`, `items`, `shipping_address`, plus:

- `tracking_numbers` — array of `{ id, carrier, tracking_number, status, checkpoints, created_at }`. `status` (always present) is the carrier-derived shipment state: `pending` | `in_transit` | `delivered`. `checkpoints` is the per-scan timeline (most recent first), each `{ checkpoint_time, status, message, city, state, country, zip, location }`. Added automatically; there is no separate tracking endpoint.
- `job_result` (once terminal) — `success`, `error`, `error_type`, `estimated_delivery`, `merchant_order_ids`, and `price_components` (`subtotal`, `tax`, `shipping`, `total`, `currency`).

```bash
curl https://api.zinc.com/orders/<order_id> \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### List orders — `GET /orders`

Returns `{ orders: [...] }`. Requires Bearer token auth. Each order's tracking numbers include `status` by default; add `?include=tracking_events` to also get the full `checkpoints` timeline.

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

See [references/errors.md](references/errors.md) for the full error code reference.

Key points:

- HTTP errors return `{ error: { code, message, details } }`
- Order processing failures appear in the order's `job_result.error_type` field
- Common issues: `max_price_exceeded`, `product_out_of_stock`, `invalid_shipping_address`
- MPP payment failures return HTTP 402 with `{ error: { code: "payment_failed", details: { reason: "..." } } }`
- HTTP 402 without `payment_failed` code means the server is issuing a payment challenge (normal MPP flow — the MPP client handles this automatically)

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
- MPP orders authorize `max_price + $1` on the agent's payment method (Stripe card/wallet or Tempo wallet) — ensure sufficient balance/credit before placing.

{{NOTES_SECTION}}## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
"""

PRODUCT_SEARCH_BLOCK = """

{{DISPLAY}} is one of the few retailers with richer product data (currently Amazon & Walmart only). For best-price comparison, use `GET /products/search?query=<term>&retailer={{SLUG}}` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer={{SLUG}}` to compare offers by **price and condition** before ordering. On the MPP rail these are `GET /agent/products/search`, `GET /agent/products/offers`, and `GET /agent/products/details` (query param `product_id=…&retailer={{SLUG}}`), $0.01 per call."""


def _dollars(cents):
    """cents -> '$45' for whole dollars, '$45.99' when there are cents."""
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def shipping_note(r):
    """Free-shipping line, from /retailers fields. Empty when the endpoint hasn't
    exposed free-shipping yet — we don't guess."""
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
        # Free shipping offered but the catalog gives no threshold — state the
        # fact without inventing a number.
        return ("**Shipping:** {{DISPLAY}} offers free shipping on qualifying orders; "
                "below the threshold shipping is added — leave room in `max_price`.")
    return (f"**Shipping:** {{{{DISPLAY}}}} ships free on orders over {_dollars(th)}; "
            "below that, shipping is added to the total — leave room in `max_price`.")


def notes_section(r):
    """The optional '## Retailer notes' block — only rendered when /retailers
    gives us something real to say (known free-shipping terms). Retailer-specific
    constraints aren't hardcoded here; the order API reports them at request time."""
    sn = shipping_note(r)
    if not sn:
        return ""
    return "## Retailer notes\n\n" + sn + "\n\n"


def render(retailer):
    out = FRONTMATTER + BODY
    out = out.replace("{{PRODUCT_SEARCH}}", PRODUCT_SEARCH_BLOCK if retailer["psearch"] else "")
    out = out.replace("{{NOTES_SECTION}}", notes_section(retailer))
    # token substitution last so it reaches injected blocks too
    out = out.replace("{{DISPLAY}}", retailer["display"])
    out = out.replace("{{SLUG}}", retailer["slug"])
    out = out.replace("{{DOMAIN}}", retailer["domain"])
    out = out.replace("{{EXAMPLE_URL}}", retailer["example_url"])
    return out


# Hand-maintained skills (SKILL.md is NOT generated) that still get the shared
# references/errors.md refreshed from the single source above.
SHARED_ERRORS_ONLY = ["universal-checkout"]

README = os.path.join(REPO_ROOT, "README.md")
TABLE_START = "<!-- SKILLS-TABLE:START (generated by tools/generate_skills.py — do not edit by hand) -->"
TABLE_END = "<!-- SKILLS-TABLE:END -->"


def update_readme_table(retailers):
    """Rewrite the skills table in README.md between the markers, so the retailer
    list there stays driven by /retailers too (not hand-maintained)."""
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
    # Guard against a mangled README: the markers must each appear exactly once,
    # in order. Otherwise partition() would silently drop content or duplicate
    # the table — fail loudly instead of corrupting the file.
    if text.count(TABLE_START) != 1 or text.count(TABLE_END) != 1:
        sys.exit(
            f"README.md must contain exactly one {TABLE_START!r} and one "
            f"{TABLE_END!r} (found {text.count(TABLE_START)} / {text.count(TABLE_END)})."
        )
    pre, _, rest = text.partition(TABLE_START)
    _, _, post = rest.partition(TABLE_END)
    with open(README, "w") as f:
        f.write(pre + block + post)


def main():
    refresh = "--refresh" in sys.argv[1:]
    catalog = load_catalog(refresh)
    retailers = build_retailers(catalog)

    written = []
    for r in retailers:
        folder = os.path.join(SKILLS_DIR, f"{r['slug']}-checkout")
        refs = os.path.join(folder, "references")
        os.makedirs(refs, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w") as f:
            f.write(render(r))
        shutil.copyfile(SHARED_ERRORS, os.path.join(refs, "errors.md"))
        written.append(f"{r['slug']}-checkout")

    # Keep the error reference in sync for hand-maintained skills too.
    for name in SHARED_ERRORS_ONLY:
        refs = os.path.join(SKILLS_DIR, name, "references")
        os.makedirs(refs, exist_ok=True)
        shutil.copyfile(SHARED_ERRORS, os.path.join(refs, "errors.md"))

    # Prune stale generated skills: a retailer dropped or renamed in the catalog
    # leaves a `<slug>-checkout/` folder that would still be installable. Only
    # `*-checkout` folders are touched; hand-maintained skills are kept.
    keep = set(written) | set(SHARED_ERRORS_ONLY)
    removed = []
    for entry in sorted(os.listdir(SKILLS_DIR)) if os.path.isdir(SKILLS_DIR) else []:
        path = os.path.join(SKILLS_DIR, entry)
        if os.path.isdir(path) and entry.endswith("-checkout") and entry not in keep:
            shutil.rmtree(path)
            removed.append(entry)

    update_readme_table(retailers)

    print(f"Generated {len(written)} retailer skills from {len(catalog)} cataloged retailers:")
    for w in written:
        print(f"  skills/{w}/")
    print(f"Refreshed errors.md for: {', '.join(SHARED_ERRORS_ONLY)}")
    if removed:
        print(f"Pruned {len(removed)} stale skill(s): {', '.join(removed)}")
    print("Updated README skills table.")


if __name__ == "__main__":
    main()
