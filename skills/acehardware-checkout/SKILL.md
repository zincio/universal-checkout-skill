---
name: acehardware-checkout
description: Buy products from Ace Hardware (acehardware.com) and manage those orders via the Zinc API (zinc.com). Use when the user wants to purchase, order, or check out an item from Ace Hardware, check Ace Hardware order status, list recent Ace Hardware orders, or place a Ace Hardware order programmatically. One API also covers Walmart, Target, Best Buy and 50+ other retailers. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for paying with crypto on-chain.
---

# Ace Hardware Checkout

Place and manage orders on Ace Hardware (acehardware.com) through the Zinc API (`https://api.zinc.com`).

> **Powered by Zinc Universal Checkout.** The same API buys from Ace Hardware and 50+ other retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order across multiple retailers from one skill, install the [`universal-checkout`](https://github.com/zincio/skills/tree/main/skills/universal-checkout) skill (`npx skills add zincio/skills --skill universal-checkout`). Live retailer list: `GET https://api.zinc.com/retailers`.

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **`TEMPO_PRIVATE_KEY` env var is set** (or user wants to pay with crypto) → Use `POST /agent/orders` with MPP. No account needed — pay per-order with on-chain crypto.
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or provide a funded Tempo wallet key.

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

## Endpoints

### Create Order (API Key) — `POST /orders`

Place a new Ace Hardware order using your API key. Requires `Authorization: Bearer $ZINC_API_KEY`.

**Required fields:**

- `products` — array of `{ url, quantity?, variant? }` objects
  - `url`: direct Ace Hardware product page URL (on acehardware.com)
  - `quantity`: integer (default 1)
  - `variant`: array of `{ label, value }` for size/color/etc.
- `shipping_address` — object with `first_name`, `last_name`, `address_line1`, `address_line2`, `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (ISO alpha-2, e.g. "US")
- `max_price` — integer, maximum price **in cents** (e.g. 5000 = $50.00)

**Optional fields:**

- `idempotency_key` — string (max 36 chars) to prevent duplicates
- `retailer_credentials_id` — short ID like `zn_acct_XXXXXXXX` (see Managed Accounts)
- `metadata` — arbitrary key-value object
- `po_number` — purchase order number string

**Response:** order object with `id` (UUID), `status`, `items`, `shipping_address`, `created_at`, `tracking_numbers`, etc.

**Order statuses:** `pending` → `in_progress` → `order_placed` | `order_failed` | `cancelled`

### Create Order (MPP) — `POST /agent/orders`

Place a Ace Hardware order using the Machine Payments Protocol. No API key required — payment is made inline via on-chain crypto.

**Same request body as `POST /orders`** (products, shipping_address, max_price).

**Billing:**
- Agent pays `max_price` upfront via crypto deposit
- A `$1.00` API fee is reserved — the retailer bot spends at most `max_price - $1`
- On success: charged `actual_price + $1`, remainder refunded via Stripe
- On failure: full `max_price` refunded via Stripe

**Response headers on success (HTTP 201):**
- `X-Api-Key` — Bearer token (e.g. `zn_live_...`) for checking order status
- `Payment-Receipt` — base64-encoded payment receipt

**Python example (full working code):**

```python
# pip install pympp
from mpp.client import Client
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent, CHAIN_ID

account = TempoAccount.from_key("0x<your-private-key>")
method = tempo(
    chain_id=CHAIN_ID,
    account=account,
    intents={"charge": ChargeIntent()},
)

async with Client(methods=[method]) as client:
    response = await client.post(
        "https://api.zinc.com/agent/orders",
        json={
            "products": [{"url": "https://www.acehardware.com/departments/tools/power-tools/drills/2012345", "quantity": 1}],
            "max_price": 5000,
            "shipping_address": {
                "first_name": "Jane",
                "last_name": "Doe",
                "address_line1": "123 Main St",
                "city": "San Francisco",
                "state": "CA",
                "postal_code": "94105",
                "phone_number": "5551234567",
                "country": "US",
            },
        },
    )

    # The Client handles the 402 → pay on-chain → retry flow automatically
    order = response.json()
    order_id = order["id"]
    api_key = response.headers["X-Api-Key"]

    # Use the API key to check status later
    status_response = await client.get(
        f"https://api.zinc.com/orders/{order_id}",
        headers={"Authorization": f"Bearer {api_key}"},
    )
```

For testnet, use `TESTNET_CHAIN_ID` instead of `CHAIN_ID`:

```python
from mpp.methods.tempo import TESTNET_CHAIN_ID
method = tempo(chain_id=TESTNET_CHAIN_ID, account=account, intents={"charge": ChargeIntent()})
```

### List Orders — `GET /orders`

Returns `{ orders: [...] }` array of order objects. Requires Bearer token auth.

### Get Order — `GET /orders/{id}`

Retrieve a single order by UUID. Requires Bearer token auth (`ZINC_API_KEY` or the `X-Api-Key` from MPP).

```bash
curl https://api.zinc.com/orders/<order_id> \
  -H "Authorization: Bearer <api_key>"
```

## Example: Place a Ace Hardware Order (API Key)

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{ "url": "https://www.acehardware.com/departments/tools/power-tools/drills/2012345", "quantity": 1 }],
    "max_price": 5000,
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

**Terminal statuses:** `order_placed`, `order_failed`, `cancelled`
**Non-terminal:** `pending`, `in_progress`

If your platform supports scheduled tasks or cron jobs, schedule a check ~7 minutes after order creation rather than polling in a loop.

## Safety

- **Always confirm with the user** before placing an order (`POST /orders` or `POST /agent/orders`). This spends real money.
- Reading orders (GET) is always safe.
- Validate that `max_price` is reasonable before submitting.
- MPP orders charge the agent's crypto wallet — ensure sufficient balance before placing.

## Retailer notes

Ace Hardware orders are placed via guest checkout — no retailer login required.


## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
