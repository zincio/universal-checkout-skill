---
name: target-checkout
description: Buy products from Target (target.com) and manage those orders via the Zinc API (zinc.com). Use when the user wants to purchase, order, or check out an item from Target, check Target order status, list recent Target orders, or place a Target order programmatically. One API also covers Walmart, Target, Best Buy and 50+ other retailers. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for paying with crypto on-chain.
---

# Target Checkout

Place and manage orders on Target (target.com) through the Zinc API (`https://api.zinc.com`).

> **Powered by Zinc Universal Checkout.** The same API buys from Target and 50+ other retailers (Amazon, Walmart, Target, Best Buy, eBay, and more). To order across multiple retailers from one skill, see the [universal checkout skill](https://github.com/zincio/universal-checkout-skill). Live retailer list: `GET https://api.zinc.com/retailers`.

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

Place a new Target order using your API key. Requires `Authorization: Bearer $ZINC_API_KEY`.

**Required fields:**

- `products` — array of `{ url, quantity?, variant? }` objects
  - `url`: direct Target product page URL (on target.com)
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

Place a Target order using the Machine Payments Protocol. No API key required — payment is made inline via on-chain crypto.

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
            "products": [{"url": "https://www.target.com/p/-/A-81905346", "quantity": 1}],
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

## Example: Place a Target Order (API Key)

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{ "url": "https://www.target.com/p/-/A-81905346", "quantity": 1 }],
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

Target supports Managed Accounts — useful for Target Circle / RedCard benefits tied to a specific account.

## Managed Accounts (Retailer Credentials)

Managed accounts let users supply their own Target login credentials instead of relying on Zinc's default accounts. This is useful for users who want more control over order processing or need account-specific settings (membership pricing, business pricing, etc.).

Docs: https://www.zinc.com/docs/v2/api-reference/managed-accounts

All endpoints require `Authorization: Bearer $ZINC_API_KEY`.

### Key Concepts

- **Order locking:** Only one order processes at a time per managed account — prevents cart conflicts.
- **Security:** Passwords and TOTP secrets are encrypted at rest and never returned in API responses.
- **Email forwarding:** Each managed account gets a dedicated Zinc email address for receiving retailer verification/2FA codes. Configure your email provider to forward Target emails to this address.

### Create Managed Account — `POST /managed-accounts`

Register Target credentials with Zinc.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Target account email |
| `password` | string | No | Target account password (encrypted at rest) |
| `retailer` | string | No | Retailer identifier (`"target"`) |
| `totp_secret` | string | No | TOTP 2FA secret key — the 64-character secret, NOT the 6-digit code |
| `retailer_config` | object | No | Retailer-specific configuration |

**Response (201):** a credential object with `id`, `short_id` (e.g., `zn_acct_a1b2c3d4`), `email`, `retailer`, `has_totp`, `has_forwarding`, `forwarding_email`, `retailer_config`, `created_at`, `updated_at`.

```bash
curl -X POST https://api.zinc.com/managed-accounts \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "myaccount@example.com",
    "password": "retailer-password",
    "retailer": "target"
  }'
```

### List / Update / Delete

- `GET /managed-accounts` → `{ credentials: [...], total: <int> }`
- `PUT /managed-accounts/{short_id}` → update any subset of fields
- `DELETE /managed-accounts/{short_id}` → `204 No Content` (don't delete a credential an active order is using)

### Using a Managed Account with Orders

Pass the `short_id` as `retailer_credentials_id` when creating an order:

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "retailer_credentials_id": "zn_acct_a1b2c3d4",
    "products": [{ "url": "https://www.target.com/p/-/A-81905346", "quantity": 1 }],
    "max_price": 5000,
    "shipping_address": { "...": "..." }
  }'
```

### Setup Tips

- **TOTP 2FA:** If the Target account has 2FA enabled, provide the TOTP secret key (the 64-character base32 string, not the rotating 6-digit code).
- **Email forwarding:** Forward only target.com emails to the Zinc forwarding address — avoid forwarding all mail.
- **Best practice:** Use a dedicated Target account for Zinc to avoid conflicts with personal orders.

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
