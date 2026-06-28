---
name: bestbuy-checkout
description: Buy products from Best Buy (bestbuy.com) and manage those orders via the Zinc API (zinc.com). Use when the user wants to purchase, order, or check out an item from Best Buy, check Best Buy order status or tracking, cancel a Best Buy order, or return a Best Buy item. One API also covers Amazon, Walmart, Target, Best Buy and 50+ other US retailers. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for per-request payments via Stripe cards/wallets or Tempo stablecoins.
---

# Best Buy Checkout

Buy, track, and return products from Best Buy (bestbuy.com) through the Zinc API (`https://api.zinc.com`). US orders.

> **Powered by Zinc Universal Checkout.** The same API buys from Best Buy and 50+ other US retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order across multiple retailers from one skill, install the [`universal-checkout`](https://github.com/zincio/skills/tree/main/skills/universal-checkout) skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: `GET https://api.zinc.com/retailers`.

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

If the user already has a Best Buy product URL, skip to **Place an order**. Otherwise search for one:

```bash
curl "https://api.zinc.com/search?q=cast+iron+skillet" \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

`GET /search` returns `{ status, query, results: [...] }` across retailers; each result has a directly **orderable `url`** plus `retailer`, `title`, `price` (cents), `stars`. Filter results to `retailer == "bestbuy"` for Best Buy-only, then pass the `url` into an order.

Paying via MPP (Stripe or Tempo, no account)? Use the metered `GET /agent/search` instead — $0.01 per call, returns a `Payment-Receipt` header; the MPP client handles the 402 → pay → retry automatically. `GET /retailers` is free.

## Place an order — `POST /orders` (or `POST /agent/orders` for MPP)

**Required fields:**

- `products` — array of product objects (see below)
- `shipping_address` — US delivery address
- `max_price` — integer, the **maximum total in cents** Zinc may spend before finalizing (your price ceiling)

**Product object:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `url` | string | ✓ | Direct Best Buy product page URL (on bestbuy.com) |
| `quantity` | integer 1–100 | — | Units to buy (default 1) |
| `variant` | array of `{ label, value }` | — | Options, e.g. `[{ "label": "Size", "value": "Large" }]` |
| `condition_in` | array | — | Allowlist of acceptable conditions |
| `condition_not_in` | array | — | Denylist of excluded conditions |

**Condition enum:** `New`, `Refurbished`, `UsedLikeNew`, `UsedVeryGood`, `UsedGood`, `UsedAcceptable`.

**Shipping address:** `first_name`, `last_name`, `address_line1`, `address_line2` (optional), `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (defaults to `US`).

**Optional order fields:** `handling_days_max` (integer ≥1 — cap on seller handling time, the lever for bounding how fast it ships), `is_gift` (boolean — suppress prices on the packing slip), `idempotency_key` (string ≤36 chars), `metadata` (object), `po_number` (string).

### Controlling price & shipping

There is no shipping-*method* picker; control cost and speed with: `max_price` (price ceiling), `condition_in` (allow used/refurbished for a cheaper qualifying offer), and `handling_days_max` (cap handling time). `max_price` is the **total** ceiling — item + shipping + tax — so leave room for shipping (see `GET /retailers` for Best Buy's free-shipping terms).

**Order statuses:** `pending` → `in_progress` → `order_placed` | `order_failed` | `cancelled` | `cancelled_by_retailer`.

**Example (API key):**

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{ "url": "https://www.bestbuy.com/<product-page>", "quantity": 1, "condition_in": ["New"] }],
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
            "products": [{"url": "https://www.bestbuy.com/<product-page>", "quantity": 1}],
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
curl https://api.zinc.com/orders/<order_id> \
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

## Retailer notes

**Shipping:** Best Buy ships free on orders over $35; below that, shipping is added to the total — leave room in `max_price`.

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
