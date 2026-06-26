---
name: universal-checkout
description: Discover, buy, track, and return products across Amazon, Walmart, Target, Best Buy, and 50+ US online retailers via the Zinc API (zinc.com). Use when the user wants to search for or buy a product, check out, check order status or tracking, cancel an order, or return an item programmatically. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for paying with crypto on-chain.
---

# Universal Checkout

Discover, buy, track, and return products across US online retailers through the Zinc API (`https://api.zinc.com`). One API covers Amazon, Walmart, Target, Best Buy, eBay, Home Depot, Lowe's, Wayfair, and 50+ more.

> Live supported-retailer list: `GET https://api.zinc.com/retailers`. If an agent only ever buys from one store, there are also retailer-specific skills (`amazon-checkout`, `walmart-checkout`, …) — see the repo README.

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **`TEMPO_PRIVATE_KEY` env var is set** (or user wants to pay with crypto) → Use the MPP `/agent/*` endpoints. No account needed — pay per call with on-chain crypto: `POST /agent/orders` to buy, and `/agent/search` · `/agent/products/*` to discover ($0.01 per data call). `GET /retailers` is free.
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or provide a funded Tempo wallet key.

All amounts are in **US cents** (e.g. `5000` = $50.00). Orders ship to US addresses.

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

## 1. Discover products (optional)

If the user gives you a product URL, skip to **Place an order**. Otherwise, find an orderable product first.

> **Two rails for data endpoints.** With an **API key**, call the endpoints below with your Bearer token (free, billed against your account). On the **MPP/crypto path** (no Zinc account), call the `/agent/*` equivalents instead — each is paid **$0.01 per call** via MPP and returns a `Payment-Receipt` header. The `pympp` `Client` handles the 402 → pay → retry flow automatically for these GETs, exactly like for orders. `GET /retailers` (the supported-retailer list) is **free** on both rails — use it to discover what's buyable before paying for anything.

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

- **Price ceiling:** `max_price` — Zinc won't finalize above it (`max_price_exceeded` otherwise).
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

### Paying with crypto (MPP) — `POST /agent/orders`

Same request body. No API key required — payment is made inline via on-chain crypto.

**Billing:** agent pays `max_price` upfront via crypto deposit; a `$1.00` API fee is reserved (bot spends at most `max_price - $1`). On success: charged `actual_price + $1`, remainder refunded via Stripe. On failure: full `max_price` refunded.

On success (HTTP 201) the response includes header `X-Api-Key` (a `zn_live_...` Bearer token for checking status) and `Payment-Receipt`.

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
    # Client handles the 402 → pay on-chain → retry flow automatically
    order = response.json()
    api_key = response.headers["X-Api-Key"]  # use for GET /orders/{id}
```

For testnet, import `TESTNET_CHAIN_ID` and pass it as `chain_id`.

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

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
