#!/usr/bin/env python3
"""Generate per-retailer Zinc checkout skills from one template.

The retailer *catalog* (which retailers exist, display name, base URL,
supported countries, free-shipping terms) is driven by the live public
`GET https://api.zinc.com/retailers` endpoint — the single source of truth — so
the skills stay in sync automatically. The endpoint deliberately does NOT carry
three things the SKILL.md template needs, so those live in a small local OVERLAY
keyed by slug:

  * example_url — an illustrative product URL for code samples
  * psearch     — whether /products/search + /products/{id}/offers cover it
  * note        — editorial, retailer-specific guidance

Usage:

    python3 tools/generate_skills.py            # generate from the committed snapshot
    python3 tools/generate_skills.py --refresh  # re-fetch /retailers, update snapshot, generate

`--refresh` writes tools/retailers.json (committed) so builds are reproducible
and catalog changes show up as a reviewable diff. A supported retailer with no
OVERLAY entry is skipped and logged loudly (it needs an example_url + note).

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

# --- Editorial overlay -----------------------------------------------------
# Per-slug fields the /retailers endpoint does not provide. `display` is an
# optional override for when the catalog's display_name isn't the polished brand
# (e.g. "Lowes" -> "Lowe's"). `fs_fallback` = (free_shipping, threshold_cents)
# used ONLY when the endpoint hasn't exposed free_shipping yet (pre-#622); once
# the endpoint returns those fields, the endpoint wins and these are ignored.
OVERLAY = {
    "amazon": {"display": "Amazon", "psearch": True, "example_url": "https://www.amazon.com/dp/B09V3KXJPB",
               "fs_fallback": (True, 3500),
               "note": "Amazon is the most broadly supported retailer — pass any amazon.com product URL. To buy a cheaper used or refurbished copy, allow those conditions via `condition_in` (e.g. `[\"New\", \"UsedLikeNew\"]`)."},
    "walmart": {"psearch": True, "example_url": "https://www.walmart.com/ip/Apple-AirPods-Pro-2/1872350654",
                "fs_fallback": (True, 3500),
                "note": "Walmart product URLs from walmart.com work directly, and product search + best-price offers are available for Walmart via the products endpoints."},
    "target": {"psearch": False, "example_url": "https://www.target.com/p/-/A-81905346",
               "fs_fallback": (True, 3500), "note": "Pass any target.com product URL."},
    "bestbuy": {"psearch": False, "example_url": "https://www.bestbuy.com/site/apple-airpods-pro-2nd-generation/4900964.p",
                "fs_fallback": (True, 3500), "note": "Pass any bestbuy.com product URL."},
    "ebay": {"psearch": False, "example_url": "https://www.ebay.com/itm/256123456789",
             "fs_fallback": (False, None),
             "note": "eBay supports fixed-price (Buy It Now) listings — pass the ebay.com item URL. Auction listings aren't supported."},
    "homedepot": {"display": "The Home Depot", "psearch": False, "example_url": "https://www.homedepot.com/p/313041081",
                  "fs_fallback": (True, 4500), "note": "Pass any homedepot.com product URL."},
    "lowes": {"display": "Lowe's", "psearch": False, "example_url": "https://www.lowes.com/pd/5013499741",
              "fs_fallback": (True, 4500), "note": "Pass any lowes.com product URL."},
    "wayfair": {"psearch": False, "example_url": "https://www.wayfair.com/furniture/pdp-w100123456.html",
                "fs_fallback": (None, None), "note": "Pass any wayfair.com product URL."},
    "1800flowers": {"display": "1-800-Flowers", "psearch": False, "example_url": "https://www.1800flowers.com/product-name-12345",
                    "fs_fallback": (False, None),
                    "note": "Great for automating gifting — set `is_gift: true` to keep prices off the packing slip, and use `metadata` to track a gift message if your workflow has one."},
    "acehardware": {"display": "Ace Hardware", "psearch": False, "example_url": "https://www.acehardware.com/departments/tools/power-tools/drills/2012345",
                    "fs_fallback": (False, None), "note": "Pass any acehardware.com product URL."},
    "pokemoncenter": {"display": "Pokémon Center", "psearch": False, "example_url": "https://www.pokemoncenter.com/product/100-10-1234",
                      "fs_fallback": (True, 2000),
                      "note": "Inventory is often limited-drop — set a sensible `max_price` and expect `product_out_of_stock` on sold-out items."},
}


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


def build_retailers(catalog):
    """Merge the live catalog with the editorial OVERLAY. Returns (configs, skipped)."""
    configs, skipped = [], []
    for raw in catalog:
        if not is_supported(raw):
            continue
        slug = raw.get("retailer")
        ov = OVERLAY.get(slug)
        if not ov:
            skipped.append(slug)
            continue
        # free-shipping: endpoint wins when it exposes the field; else fallback.
        if "free_shipping" in raw:
            fs, th = raw.get("free_shipping"), raw.get("free_shipping_threshold_cents")
        else:
            fs, th = ov["fs_fallback"]
        configs.append({
            "slug": slug,
            "display": ov.get("display") or raw.get("display_name") or slug,
            "domain": raw.get("base_url") or slug,
            "example_url": ov["example_url"],
            "psearch": ov["psearch"],
            "free_shipping": fs,
            "ship_threshold_cents": th,
            "note": ov["note"],
        })
    return configs, skipped

# --- Template --------------------------------------------------------------
# Tokens: {{DISPLAY}} {{SLUG}} {{DOMAIN}} {{EXAMPLE_URL}}
# {{PRODUCT_SEARCH}} and {{RETAILER_NOTE}} are assembled in Python.

FRONTMATTER = """---
name: {{SLUG}}-checkout
description: Buy products from {{DISPLAY}} ({{DOMAIN}}) and manage those orders via the Zinc API (zinc.com). Use when the user wants to purchase, order, or check out an item from {{DISPLAY}}, check {{DISPLAY}} order status or tracking, cancel a {{DISPLAY}} order, or return a {{DISPLAY}} item. One API also covers Amazon, Walmart, Target, Best Buy and 50+ other US retailers. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for paying with crypto on-chain.
---
"""

BODY = """
# {{DISPLAY}} Checkout

Buy, track, and return products from {{DISPLAY}} ({{DOMAIN}}) through the Zinc API (`https://api.zinc.com`). US orders.

> **Powered by Zinc Universal Checkout.** The same API buys from {{DISPLAY}} and 50+ other US retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order across multiple retailers from one skill, install the [`universal-checkout`](https://github.com/zincio/skills/tree/main/skills/universal-checkout) skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: `GET https://api.zinc.com/retailers`.

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **`TEMPO_PRIVATE_KEY` env var is set** (or user wants to pay with crypto) → Use the MPP `/agent/*` endpoints. No account needed — pay per call with on-chain crypto: `POST /agent/orders` to buy, and `/agent/search` to discover ($0.01 per data call). `GET /retailers` is free.
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or provide a funded Tempo wallet key.

All amounts are in **US cents** (e.g. `5000` = $50.00).

## Authentication

### API Key Auth

```
Authorization: Bearer $ZINC_API_KEY
```

### MPP Auth (Machine Payments Protocol)

MPP uses a challenge-response flow — no API key needed upfront:

1. Send `POST /agent/orders` with no auth → receive HTTP 402 with payment challenge
2. The `pympp` client library resolves the challenge automatically (signs and submits an on-chain transaction)
3. The request is retried with payment credentials → HTTP 201 order created
4. Save the `X-Api-Key` response header — use it as a Bearer token for `GET /orders/{id}`

The `pympp` `Client` handles steps 1-3 automatically. You just make one `client.post()` call.

## Find a product (optional)

If the user already has a {{DISPLAY}} product URL, skip to **Place an order**. Otherwise search for one:

```bash
curl "https://api.zinc.com/search?q=cast+iron+skillet" \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

`GET /search` returns `{ status, query, results: [...] }` across retailers; each result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), `stars`. Filter results to `retailer == "{{SLUG}}"` for {{DISPLAY}}-only, then pass the `url` into an order.

Paying with crypto (MPP, no account)? Use the metered `GET /agent/search` instead — $0.01 per call, returns a `Payment-Receipt` header; the `pympp` `Client` handles the 402 → pay → retry automatically. `GET /retailers` is free.{{PRODUCT_SEARCH}}

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

There is no shipping-*method* picker; control cost and speed with: `max_price` (price ceiling), `condition_in` (allow used/refurbished for a cheaper qualifying offer), and `handling_days_max` (cap handling time). `max_price` is the **total** ceiling — item + shipping + tax — so leave room for shipping when the order is below {{DISPLAY}}'s free-shipping threshold (see Retailer notes).

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

### Paying with crypto (MPP) — `POST /agent/orders`

Same request body, no API key. Agent pays `max_price` upfront via crypto deposit; a `$1.00` API fee is reserved (bot spends at most `max_price - $1`). On success: charged `actual_price + $1`, remainder refunded via Stripe. On failure: full refund. The HTTP 201 response includes header `X-Api-Key` (a `zn_live_...` Bearer token for status checks) and `Payment-Receipt`.

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
    # Client handles the 402 → pay on-chain → retry flow automatically
    order = response.json()
    api_key = response.headers["X-Api-Key"]  # use for GET /orders/{id}
```

For testnet, import `TESTNET_CHAIN_ID` and pass it as `chain_id`.

## Track & manage orders

### Get order — `GET /orders/{id}`

Retrieve a single order by UUID (Bearer token: `ZINC_API_KEY` or the MPP `X-Api-Key`). The response includes `status`, `items`, `shipping_address`, plus:

- `tracking_numbers` — array of `{ id, carrier, tracking_number, created_at }` (carrier e.g. `ups`, `fedex`, `usps`, `amazon`). Added automatically; there is no separate tracking endpoint.
- `job_result` (once terminal) — `success`, `error`, `error_type`, `estimated_delivery`, `merchant_order_ids`, and `price_components` (`subtotal`, `tax`, `shipping`, `total`, `currency`).

```bash
curl https://api.zinc.com/orders/<order_id> \\
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### List orders — `GET /orders`

Returns `{ orders: [...] }`. Requires Bearer token auth.

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
- HTTP 402 without `payment_failed` code means the server is issuing a payment challenge (normal MPP flow — the `pympp` client handles this automatically)

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
- Validate that `max_price` is reasonable before submitting.
- MPP orders charge the agent's crypto wallet — ensure sufficient balance before placing.

## Retailer notes

{{RETAILER_NOTE}}

{{SHIPPING_NOTE}}

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
"""

PRODUCT_SEARCH_BLOCK = """

For richer {{DISPLAY}} results and best-price comparison, use `GET /products/search?query=<term>&retailer={{SLUG}}` (returns `product_id`, `price`, `ship_price`, `stars`, …) and `GET /products/{product_id}/offers?retailer={{SLUG}}` to compare offers by **price and condition** before ordering. On the MPP rail these are `GET /agent/products/search`, `GET /agent/products/offers`, and `GET /agent/products/details` (query param `product_id=…&retailer={{SLUG}}`), $0.01 per call."""


def shipping_note(r):
    """Free-shipping line for the Retailer notes section, from /retailers fields."""
    fs = r.get("free_shipping")
    th = r.get("ship_threshold_cents")
    if fs is None:
        return ("**Shipping:** check `GET /retailers` for {{DISPLAY}}'s current "
                "free-shipping terms, and include any shipping cost in `max_price`.")
    if fs is False:
        return ("**Shipping:** {{DISPLAY}} has no flat free-shipping threshold — "
                "shipping is added per order, so leave room for it in `max_price`.")
    if th == 0:
        return "**Shipping:** {{DISPLAY}} ships free on all orders."
    return (f"**Shipping:** {{{{DISPLAY}}}} ships free on orders over ${th // 100}. "
            "For cheaper items, shipping is added to the order total, so leave room "
            "for it in `max_price`. (Live terms: `GET /retailers`.)")


def render(retailer):
    out = FRONTMATTER + BODY
    out = out.replace("{{PRODUCT_SEARCH}}", PRODUCT_SEARCH_BLOCK if retailer["psearch"] else "")
    out = out.replace("{{RETAILER_NOTE}}", retailer.get("note", ""))
    out = out.replace("{{SHIPPING_NOTE}}", shipping_note(retailer))
    # token substitution last so it reaches injected blocks too
    out = out.replace("{{DISPLAY}}", retailer["display"])
    out = out.replace("{{SLUG}}", retailer["slug"])
    out = out.replace("{{DOMAIN}}", retailer["domain"])
    out = out.replace("{{EXAMPLE_URL}}", retailer["example_url"])
    return out


# Hand-maintained skills (SKILL.md is NOT generated) that still get the shared
# references/errors.md refreshed from the single source above.
SHARED_ERRORS_ONLY = ["universal-checkout"]


def main():
    refresh = "--refresh" in sys.argv[1:]
    catalog = load_catalog(refresh)
    retailers, skipped = build_retailers(catalog)

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

    print(f"Generated {len(written)} retailer skills from {len(catalog)} cataloged retailers:")
    for w in written:
        print(f"  skills/{w}/")
    print(f"Refreshed errors.md for: {', '.join(SHARED_ERRORS_ONLY)}")
    if skipped:
        print(f"\n⚠ Supported but SKIPPED (no OVERLAY entry — add example_url + note): "
              f"{', '.join(skipped)}")


if __name__ == "__main__":
    main()
