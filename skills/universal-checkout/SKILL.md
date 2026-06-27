---
name: universal-checkout
description: Discover, buy, track, and return products across Amazon, Walmart, Target, Best Buy, and 50+ US online retailers via the Zinc API (zinc.com). Use when the user wants to search for or buy a product, check out, check order status or tracking, cancel an order, or return an item programmatically. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for per-request payments via Stripe cards/wallets or Tempo stablecoins.
---

# Universal Checkout

Discover, buy, track, and return products across US online retailers through the Zinc API (`https://api.zinc.com`). One API covers Amazon, Walmart, Target, Best Buy, eBay, Home Depot, Lowe's, Wayfair, and 50+ more.

> Live supported-retailer list: `GET https://api.zinc.com/retailers` (free, no auth) — a flat catalog, one object per retailer, with `retailer` (slug), `display_name`, `supported`, `base_url`, `supported_countries`, and free-shipping info: `free_shipping` (bool) and `free_shipping_threshold_cents` (`0` = always free; a positive int = free over that many cents; `null` = no flat free-shipping offer). If an agent only ever buys from one store, there are also retailer-specific skills (`amazon-checkout`, `walmart-checkout`, …) — see the repo README.

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **MPP — no account needed** → Use the `/agent/*` endpoints; pay per request via **Tempo stablecoins** (`TEMPO_PRIVATE_KEY`, on-chain) or **Stripe** (cards/wallets via Stripe Link). `POST /agent/orders` to buy; `/agent/search` · `/agent/products/*` to discover ($0.01 per data call). `GET /retailers` is free.
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or set up an MPP payment method (Tempo wallet or Stripe). Try it without code at <https://agent.zinc.com>.

All amounts are in **US cents** (e.g. `5000` = $50.00). Orders ship to US addresses.

## Authentication

### API Key Auth

```
Authorization: Bearer $ZINC_API_KEY
```

### MPP Auth (Machine Payments Protocol)

MPP is an open standard for HTTP 402 machine-to-machine payments (spec: <https://mpp.dev>) — no API key needed upfront:

1. Send the request (e.g. `POST /agent/orders`) with no `Authorization` header → receive HTTP `402 Payment Required` with one `WWW-Authenticate: Payment …` header per supported payment method
2. The MPP client picks a method, completes payment, and obtains a credential
3. Retry with `Authorization: Payment <credential>` → success
4. For orders, save the `X-Api-Key` response header — a Bearer token (scoped to that order) for `GET /orders/{id}`

Client libraries handle steps 1–3 automatically: **Python** `pip install pympp`, **TypeScript** `npm install mppx viem`, **CLI** `npx mppx <url> --method POST --body '…'`.

**Supported payment methods** (advertised in the `WWW-Authenticate` headers; the client auto-selects):

| Method | Description |
|--------|-------------|
| Stripe | Cards and wallets via Stripe Link (Shared Payment Tokens) |
| Tempo  | Stablecoin payments on-chain |

> **Header-parsing gotcha:** many HTTP clients collapse repeated response headers into one comma-joined string, which corrupts the `WWW-Authenticate` param list. If parsing the challenge yourself, read the **raw** header list (in Python `httpx`, `resp.headers.raw`) and select by `method=`.

## 1. Discover products (optional)

If the user gives you a product URL, skip to **Place an order**. Otherwise, find an orderable product first.

> **Two rails for data endpoints.** With an **API key**, call the endpoints below with your Bearer token (free, billed against your account). On the **MPP path** (no Zinc account, Stripe or Tempo), call the `/agent/*` equivalents instead — each is paid **$0.01 per call** via MPP and returns a `Payment-Receipt` header. The MPP client handles the 402 → pay → retry flow automatically for these GETs, exactly like for orders. `GET /retailers` (the supported-retailer list) is **free** on both rails — use it to discover what's buyable before paying for anything.

### Cross-retailer search — `GET /search` · MPP: `GET /agent/search`

Search across retailers (Amazon, Walmart, Target, Best Buy, Home Depot, Lowe's, Costco, eBay, Wayfair, Macy's, and more). Results are ranked by a quality signal (rating + review volume, price as tiebreaker) and woven across retailers so one doesn't dominate.

```bash
# API key
curl "https://api.zinc.com/search?q=cast+iron+skillet" \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

Returns `{ status, query, results: [...] }`. Each result has a directly **orderable `url`** plus `retailer`, `title`, `image`, `brand`, `price` (cents), `stars`, `num_reviews`, `available`. Pass a result's `url` straight into an order. *(Beta: no sort/filter params yet; coverage varies by query.)*

### Product search, offers & details (Amazon & Walmart)

Best-price comparison and richer product data, on either rail:

| Purpose | API key | MPP ($0.01/call) |
|---------|---------|------------------|
| Per-retailer search | `GET /products/search?query=<term>&retailer=amazon\|walmart&page=<n>` | `GET /agent/products/search?query=…&retailer=…` |
| Offers / best price | `GET /products/{product_id}/offers?retailer=amazon\|walmart` | `GET /agent/products/offers?product_id=…&retailer=…` |
| Product details | `GET /products/{product_id}?retailer=amazon\|walmart` | `GET /agent/products/details?product_id=…&retailer=…` |

- **Search** returns `product_id`, `price`, `ship_price`, `prime`, `stars`, `num_reviews`, `available`, etc.
- **Offers** lists the available offers for a product so you can compare **price and condition** and pick the cheapest acceptable one before ordering.
- Offers/details accept optional `max_age` / `newer_than` (seconds, mutually exclusive) and `async=true` (return immediately with `status=processing`).
- Agent (`/agent/*`) endpoints validate params *after* payment — but a *paying* caller with a bad param gets a `422` and is **not** charged; an unpaid/partial probe gets a `402` challenge.

## 2. Place an order — `POST /orders` (or `POST /agent/orders` for MPP)

**Required fields:**

- `products` — array of product objects (see below)
- `shipping_address` — US delivery address (see below)
- `max_price` — integer, the **maximum total in cents** Zinc may spend before finalizing (your price ceiling)

**Product object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✓ | Direct product page URL on a supported retailer |
| `quantity` | integer 1–100 | — | Units to buy (default 1) |
| `variant` | array of `{ label, value }` | — | Options, e.g. `[{ "label": "Size", "value": "Large" }]` |
| `condition_in` | array | — | Allowlist of acceptable conditions |
| `condition_not_in` | array | — | Denylist of excluded conditions |

**Condition enum:** `New`, `Refurbished`, `UsedLikeNew`, `UsedVeryGood`, `UsedGood`, `UsedAcceptable`.

**Shipping address:** `first_name`, `last_name`, `address_line1`, `address_line2` (optional), `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (defaults to `US`).

**Optional order fields:**

| Field | Type | Description |
|-------|------|-------------|
| `handling_days_max` | integer ≥1 | Cap on seller handling time — the lever for bounding how fast it ships. Omit for no limit. |
| `is_gift` | boolean | Suppress prices on the packing slip (default `false`). |
| `idempotency_key` | string ≤36 chars | Prevents duplicate orders; auto-generated if omitted. |
| `metadata` | object | Arbitrary key-value pairs for your own reference. |
| `po_number` | string | Purchase order reference. |

### Controlling price & shipping

There is no shipping-*method* picker; control cost and speed with these:

- **Price ceiling:** `max_price` — Zinc won't finalize above it (`max_price_exceeded` otherwise). It's the **total** ceiling: item + shipping + tax.
- **Budget for shipping:** below a retailer's free-shipping threshold, shipping is added to the total — leave room in `max_price`. Each retailer's `free_shipping` / `free_shipping_threshold_cents` is in `GET /retailers` (e.g. Amazon/Walmart/Target/Best Buy free over $35, Home Depot/Lowe's over $45).
- **Best/cheapest price:** allow used or refurbished via `condition_in` (e.g. `["New", "UsedLikeNew"]`) so the bot can take a cheaper qualifying offer; use the **offers** endpoint above to compare first.
- **Shipping speed:** `handling_days_max` caps seller handling time.

**Order statuses:** `pending` → `in_progress` → `order_placed` | `order_failed` | `cancelled` | `cancelled_by_retailer`.

**Example (API key):**

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{ "url": "https://www.amazon.com/dp/B09V3KXJPB", "quantity": 1, "condition_in": ["New"] }],
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

Same request body. No API key required — payment is made inline via Stripe or Tempo.

**Billing:**
- Agent authorizes `max_price + $1.00` upfront (the `$1` is the Zinc API fee, so the full `max_price` stays available to the retailer).
- **Validation runs before payment:** an invalid product URL, retailer, country, or address returns HTTP 400 with **no charge** — the credential stays reusable for a corrected retry.
- On success: charged `actual_total + $1`; if `actual_total < max_price`, the difference is auto-refunded. On failure (out of stock, retailer rejects, etc.): full refund. Refunds are issued server-side — no agent action needed.

On success (HTTP 201) the response includes `X-Api-Key` (a `zn_live_...` Bearer token, scoped to this order) and `Payment-Receipt`.

**Quick test (CLI):**

```bash
npx mppx https://api.zinc.com/agent/orders --method POST --body '{
  "products": [{"url": "https://www.amazon.com/dp/B09V3KXJPB"}],
  "max_price": 5000,
  "shipping_address": { "first_name": "Jane", "last_name": "Doe", "address_line1": "123 Main St", "city": "San Francisco", "state": "CA", "postal_code": "94105", "phone_number": "5551234567", "country": "US" }
}'
```

**Python (Tempo) — `pympp`:**

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
            "products": [{"url": "https://www.amazon.com/dp/B09V3KXJPB", "quantity": 1}],
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

For testnet, import `TESTNET_CHAIN_ID` and pass it as `chain_id`. TypeScript is equivalent via `mppx` (`Mppx.create({ methods: [tempo({ account, maxDeposit: "1" })] })`, then `mppx.fetch(...)`).

**Stripe (Shared Payment Tokens):** to integrate Stripe directly without `mppx`/`pympp` (e.g. minting SPTs via the [Stripe Link API](https://link.com/agents)), see <https://docs.zinc.com/v2/mpp#using-stripe-with-mpp>. The spend-request amount must equal `max_price + $1.00`, and the resubmit credential is an MPP `Credential` object (a `ChallengeEcho` + `{"type": "spt", "shared_payment_granted_token": "spt_xxx"}`), not the raw SPT — `pympp` has helpers to build it.

## 3. Track & manage orders

### Get order — `GET /orders/{id}`

Retrieve a single order by UUID (Bearer token: `ZINC_API_KEY` or the MPP `X-Api-Key`). The response carries everything, including:

- `status`, `attempts`, `items`, `shipping_address`
- `tracking_numbers` — array of `{ id, carrier, tracking_number, created_at }`. Carrier is e.g. `ups`, `fedex`, `usps`, `amazon`, `dhl`. Tracking is added automatically — there is no separate tracking endpoint.
- `job_result` — once terminal: `success`, `error`, `error_type`, `estimated_delivery`, `merchant_order_ids`, and `price_components` (`subtotal`, `tax`, `shipping`, `total`, `currency`, `line_items`).

```bash
curl https://api.zinc.com/orders/<order_id> \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### List orders — `GET /orders`

Returns `{ orders: [...] }`. Requires Bearer token auth.

### Cancel order — `POST /orders/{id}/cancel`

Cancels an order **only while `pending`** (still queued). Once it's `in_progress` or done, it can't be cancelled. Returns `204 No Content` on success.

```bash
curl -X POST https://api.zinc.com/orders/<order_id>/cancel \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

## 4. Returns — `POST /returns`

Open a return against a placed order. Requires Bearer token auth.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `order_id` | UUID | ✓ | The order being returned |
| `items` | array of `{ order_item_id, quantity }` | ✓ | Items to return (quantity 1–100; `order_item_id` comes from the order's `items`) |
| `reason` | enum | ✓ | `damaged`, `not_delivered`, `empty_box`, `wrong_item`, `defective`, `not_as_described`, `wrong_size`, `no_longer_needed`, `forced_cancellation`, `other` |
| `notes` | string ≤2000 | — | Free-text detail |

**Response (201):** `{ id, order_id, status, reason, notes, resolution_notes, items, label_urls, merchant_return_id, created_at, updated_at }`. Return `status`: `open` → `approved` | `denied` | `credited`. Print/ship via the URLs in `label_urls`.

```bash
curl -X POST https://api.zinc.com/returns \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "8c2d...",
    "items": [{ "order_item_id": "a1b2...", "quantity": 1 }],
    "reason": "damaged",
    "notes": "Arrived with a crushed corner."
  }'
```

Also: `GET /returns` (list) and `GET /returns/{id}` (single).

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
- Validate that `max_price` is reasonable before submitting.
- MPP orders authorize `max_price + $1` on the agent's payment method (Stripe card/wallet or Tempo wallet) — ensure sufficient balance/credit before placing.

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
