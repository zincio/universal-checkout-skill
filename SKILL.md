---
name: zinc-orders
description: Place, list, and retrieve orders via the Zinc API (zinc.com). Use when the user wants to buy a product from an online retailer, check order status, list recent orders, or anything involving the Zinc e-commerce ordering API. Supports API key auth (ZINC_API_KEY) or Machine Payments Protocol (MPP) for per-request payments via Stripe cards/wallets or Tempo stablecoins.
---

# Zinc Orders

Place and manage orders on online retailers through the Zinc API (`https://api.zinc.com`).

## Quick Start

**Which auth method should I use?**

- **`ZINC_API_KEY` env var is set** → Use `POST /orders` with Bearer token auth. This is the standard flow for pre-registered users.
- **MPP — no account needed** → Use `POST /agent/orders`. Pay per-order via:
  - **Tempo stablecoins** (`TEMPO_PRIVATE_KEY` env var, on-chain crypto)
  - **Stripe** (cards/wallets via Stripe Link / Shared Payment Tokens)
- **Neither is set** → Ask the user to either sign up at <https://app.zinc.com> for an API key, or set up an MPP payment method (Tempo wallet or Stripe).

Try MPP without writing code at <https://agent.zinc.com> (interactive playground).

## Authentication

### API Key Auth

```
Authorization: Bearer $ZINC_API_KEY
```

### MPP Auth (Machine Payments Protocol)

MPP is an open standard for HTTP 402 machine-to-machine payments (spec: <https://mpp.dev>). The flow:

1. Send `POST /agent/orders` with no `Authorization` header → receive HTTP `402 Payment Required` with one `WWW-Authenticate: Payment ...` header per supported payment method
2. The MPP client picks a method, completes payment, and obtains a credential
3. Request is retried with `Authorization: Payment <credential>` → HTTP 201 order created
4. Save the `X-Api-Key` response header — use it as a Bearer token for `GET /orders/{id}` (scoped to that order)

Client libraries handle steps 1–3 automatically:

- **TypeScript:** `npm install mppx viem`
- **Python:** `pip install pympp`
- **CLI (quick test):** `npx mppx <url> --method POST --body '...'`

**Supported payment methods:**

| Method | Description |
| ------ | ----------- |
| Stripe | Cards and wallets via Stripe Link (Shared Payment Tokens) |
| Tempo | Stablecoin payments via Tempo on-chain |

The available methods are advertised in the `WWW-Authenticate` headers of the 402 response. The client selects a compatible one automatically.

> **Header parsing gotcha:** Many HTTP clients collapse repeated response headers into a single comma-joined string, which corrupts the `WWW-Authenticate` param list. If you're parsing the challenge yourself, read the **raw** header list (in Python `httpx`, use `resp.headers.raw`) and select by `method=`.

## Endpoints

### Create Order (API Key) — `POST /orders`

Place a new order using your API key. Requires `Authorization: Bearer $ZINC_API_KEY`.

**Required fields:**

- `products` — array of `{ url, quantity?, variant? }` objects
  - `url`: direct product page URL on a supported retailer
  - `quantity`: integer (default 1)
  - `variant`: array of `{ label, value }` for size/color/etc.
- `shipping_address` — object with `first_name`, `last_name`, `address_line1`, `address_line2`, `city`, `state` (2-letter), `postal_code`, `phone_number`, `country` (ISO alpha-2, e.g. "US")
- `max_price` — integer, maximum price **in cents** (e.g. 5000 = $50.00)

**Optional fields:**

- `idempotency_key` — string (max 36 chars) to prevent duplicates
- `retailer_credentials_id` — short ID like `zn_acct_XXXXXXXX`
- `metadata` — arbitrary key-value object
- `po_number` — purchase order number string

**Response:** order object with `id` (UUID), `status`, `items`, `shipping_address`, `created_at`, `tracking_numbers`, etc.

**Order statuses:** `pending` → `in_progress` → `order_placed` | `order_failed` | `cancelled`

### Create Order (MPP) — `POST /agent/orders`

Place an order using the Machine Payments Protocol. No API key required — payment is made inline via Stripe or Tempo.

**Same request body as `POST /orders`** (products, shipping_address, max_price).

**Billing:**
- Agent authorizes `max_price + $1.00` upfront (the `$1` is the Zinc API fee, so the full `max_price` remains available to the retailer)
- **Validation runs before payment:** if product URL, retailer, country, or address is invalid, Zinc returns HTTP 400 with **no charge applied** — the credential/SPT stays reusable for a corrected retry
- On success: charged `actual_total + $1`; if `actual_total < max_price`, Zinc auto-refunds the difference
- On failure (out of stock, retailer rejects, etc.): full refund of the charged amount

Refunds (Stripe) are issued server-side against the original PaymentIntent — no agent-side action required.

**Response headers on success (HTTP 201):**
- `X-Api-Key` — Bearer token (e.g. `zn_live_...`), scoped to this order, for `GET /orders/{id}`
- `Payment-Receipt` — base64-encoded MPP payment receipt

**Quick test with the `mppx` CLI:**

```bash
npx mppx https://api.zinc.com/agent/orders \
  --method POST \
  --body '{
    "products": [{"url": "https://www.amazon.com/dp/B09V3KXJPB"}],
    "max_price": 5000,
    "shipping_address": { "first_name": "Jane", "last_name": "Doe",
      "address_line1": "123 Main St", "city": "San Francisco", "state": "CA",
      "postal_code": "94105", "phone_number": "5551234567", "country": "US" }
  }'
```

**Python (Tempo) — `pympp`:**

```python
# pip install pympp
from mpp.client import Client
from mpp.methods.tempo import tempo, TempoAccount, ChargeIntent, CHAIN_ID

account = TempoAccount.from_key("0x<your-private-key>")
method = tempo(
    chain_id=CHAIN_ID,  # use TESTNET_CHAIN_ID for testnet
    account=account,
    intents={"charge": ChargeIntent()},
)

async with Client(methods=[method]) as client:
    response = await client.post(
        "https://api.zinc.com/agent/orders",
        json={
            "products": [{"url": "https://www.amazon.com/dp/B09V3KXJPB", "quantity": 1}],
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

    # Client handles the 402 → pay → retry flow automatically
    order = response.json()
    api_key = response.headers["X-Api-Key"]
```

**TypeScript (Tempo) — `mppx`:**

```typescript
// npm install mppx viem
import { Mppx, tempo } from "mppx/client";
import { privateKeyToAccount } from "viem/accounts";

const mppx = Mppx.create({
  methods: [tempo({
    account: privateKeyToAccount("0x..."),
    maxDeposit: "1",
  })],
});

const response = await mppx.fetch("https://api.zinc.com/agent/orders", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    products: [{ url: "https://www.amazon.com/dp/B09V3KXJPB" }],
    max_price: 5000,
    shipping_address: { /* ... */ },
  }),
});
const apiKey = response.headers.get("X-Api-Key");
```

**Stripe (Shared Payment Tokens):** if you want to integrate with Stripe directly (without `mppx`/`pympp`) — for example, minting SPTs via the [Stripe Link API](https://link.com/agents) or `link-cli` — see <https://docs.zinc.com/v2/mpp#using-stripe-with-mpp> for the wire-level flow. Key points: the spend-request amount must equal `max_price + $1.00`, and the resubmit credential is an MPP `Credential` object (a `ChallengeEcho` + `{"type": "spt", "shared_payment_granted_token": "spt_xxx"}` payload), not the raw SPT. `pympp` provides helpers to construct it correctly.

### List Orders — `GET /orders`

Returns `{ orders: [...] }` array of order objects. Requires Bearer token auth.

### Get Order — `GET /orders/{id}`

Retrieve a single order by UUID. Requires Bearer token auth (`ZINC_API_KEY` or the `X-Api-Key` from MPP).

```bash
curl https://api.zinc.com/orders/<order_id> \
  -H "Authorization: Bearer <api_key>"
```

## Example: Place an Order (API Key)

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "products": [{ "url": "https://www.amazon.com/dp/B09V3KXJPB", "quantity": 1 }],
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
- MPP orders authorize `max_price + $1` on the agent's payment method (Stripe card/wallet or Tempo wallet) — ensure sufficient balance/credit before placing.

## Managed Accounts (Retailer Credentials)

Managed accounts let users supply their own retailer login credentials (e.g., Amazon) instead of relying on Zinc's default accounts. This is useful for users who want more control over order processing or need to use accounts with specific settings (Prime, business pricing, etc.).

Docs: https://www.zinc.com/docs/v2/api-reference/managed-accounts

All endpoints require `Authorization: Bearer $ZINC_API_KEY`.

### Key Concepts

- **Order locking:** Only one order processes at a time per managed account — prevents cart conflicts.
- **Security:** Passwords and TOTP secrets are encrypted at rest and never returned in API responses.
- **Email forwarding:** Each managed account gets a dedicated Zinc email address for receiving retailer verification/2FA codes. Configure your email provider to forward retailer emails to this address.

### Create Managed Account — `POST /managed-accounts`

Register retailer credentials with Zinc.

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | Yes | Retailer account email |
| `password` | string | No | Retailer account password (encrypted at rest) |
| `retailer` | string | No | Retailer identifier (e.g., `"amazon"`); null for default |
| `totp_secret` | string | No | TOTP 2FA secret key — the 64-character secret, NOT the 6-digit code |
| `retailer_config` | object | No | Retailer-specific configuration |

**Response (201):** Returns a credential object with `id`, `short_id` (e.g., `zn_acct_a1b2c3d4`), `email`, `retailer`, `has_totp`, `has_forwarding`, `forwarding_email`, `retailer_config`, `created_at`, `updated_at`.

```bash
curl -X POST https://api.zinc.com/managed-accounts \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "myaccount@example.com",
    "password": "retailer-password",
    "retailer": "amazon"
  }'
```

### List Managed Accounts — `GET /managed-accounts`

Returns `{ credentials: [...], total: <int> }` with all retailer credentials for your account.

```bash
curl https://api.zinc.com/managed-accounts \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### Update Managed Account — `PUT /managed-accounts/{short_id}`

Update credentials by `short_id`. All body fields are optional — only provided values are updated.

| Field | Type | Description |
|-------|------|-------------|
| `email` | string | New email |
| `password` | string | New password |
| `retailer` | string | New retailer |
| `totp_secret` | string | New TOTP secret |
| `retailer_config` | object | New retailer config |

```bash
curl -X PUT https://api.zinc.com/managed-accounts/zn_acct_a1b2c3d4 \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "password": "new-password" }'
```

### Delete Managed Account — `DELETE /managed-accounts/{short_id}`

Permanently deletes credentials. Returns `204 No Content` on success.

**Warning:** Deleting credentials that are actively in use by a processing order may cause the order to fail.

```bash
curl -X DELETE https://api.zinc.com/managed-accounts/zn_acct_a1b2c3d4 \
  -H "Authorization: Bearer $ZINC_API_KEY"
```

### Using Managed Accounts with Orders

Pass the `short_id` as `retailer_credentials_id` when creating an order:

```bash
curl -X POST https://api.zinc.com/orders \
  -H "Authorization: Bearer $ZINC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "retailer_credentials_id": "zn_acct_a1b2c3d4",
    "products": [{ "url": "https://www.amazon.com/dp/B09V3KXJPB", "quantity": 1 }],
    "max_price": 5000,
    "shipping_address": { ... }
  }'
```

### Setup Tips

- **TOTP 2FA:** If the retailer account has 2FA enabled, provide the TOTP secret key (the 64-character base32 string, not the rotating 6-digit code). On Amazon: Login & Security → Enable 2FA → "Can't scan the barcode?" → copy the secret.
- **Email forwarding:** Set up email filters to forward only retailer domain emails (e.g., from `amazon.com`) to the Zinc forwarding address — avoid forwarding all mail.
- **Disable passkeys:** Passkeys interfere with automated login. On Amazon: Login & Security → Passkey → delete any passkeys. Use password + TOTP only.
- **Best practice:** Create a dedicated retailer account for Zinc to avoid conflicts with personal orders.

## Support

- Email: support@zinc.com
- Book a call with our CEO: https://cal.com/zinc-ian/15min
- Discord: https://discord.gg/cuXgfczYfj
