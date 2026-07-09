---
name: send-donuts
description: Send a box of Krispy Kreme donuts (doughnuts) to someone by mail, paid with your own credit card via Stripe Link — driven entirely from the terminal. Use when the user wants to send donuts, doughnuts, treats, or a thank-you gift to a lead, prospect, customer, colleague, or friend — e.g. "send donuts to Jane at Acme", "mail a dozen glazed to our new customer", "send a thank-you gift to the team". Orders are placed and shipped through the Zinc API; payment is a Stripe Link Shared Payment Token via the create-payment-credential (link-cli) skill.
allowed-tools:
  - Bash(curl:*)
  - Bash(link-cli:*)
  - Bash(npx:*)
---

# Send a Dozen

Send Krispy Kreme donuts to anyone by mail, from the terminal, paid with your own credit card. You pick a box, give a recipient address, confirm, and pay with **Stripe Link** — the order is placed and shipped through **Zinc**.

> **Prerequisite: the `create-payment-credential` skill (Stripe `link-cli`) must be installed and authenticated.** Install: `npm install -g @stripe/link-cli`; check with `link-cli auth status`; if not logged in, `link-cli auth login --client-name "send-donuts"` and approve in the Link app. Payment is a one-time **Shared Payment Token (SPT)** minted from your Link card — no crypto wallet needed.

Everything here is plain HTTP + a CLI, runnable by hand. Amounts are in **US cents** (`2000` = $20.00). Ships to US addresses.

## What it costs

The box price + shipping + tax, plus a **$1 Zinc fee** (the machine-payment fee on this rail). Krispy Kreme fulfills a **dozen** per order.

| SKU | Box | Product URL (passed to Zinc) | `max_price` | All-in estimate |
|-----|-----|------------------------------|-------------|-----------------|
| `original-glazed-dozen` | Original Glazed Dozen (12) | `https://www.krispykreme.com/menu/doughnuts/all/original-glazed-doughnut` | `2000` | **≈ $20.99** ($19.99 + $1) |

> Verified via a real Zinc order (glazed dozen delivered = $19.99). More flavors can be added — each new URL should be confirmed with one real order first, since Zinc ships a **dozen of that flavor** at the given product URL. Set `max_price` a little above the expected delivered total; Zinc captures the actual total (+ $1) and releases the rest.

## Steps, in order

### 1. Pick a box

Use the table above (or accept a SKU/flavor the user already named). Present the **all-in estimate**, not the bare box price.

### 2. Gather the recipient address and the sender's phone

- **Address** — if the user gave one, use it. Otherwise research the recipient's **company shipping address** (HQ or the named office) via web search and confirm it back before proceeding.
- **Phone** — **always the sender's own real phone**, never the recipient's (Uber-Eats pattern: delivery issues route to the sender). Zinc **rejects invalid/placeholder numbers** (e.g. `555…`), so use a real one. Ask if you don't have it.

### 3. Confirm before paying — MANDATORY

Before anything that spends money, show the user and wait for an explicit **"yes"**:

- the **box** and its **all-in estimate** in dollars (e.g. `$20.99`),
- the **full recipient address** as it will ship,
- the **gift note** (if any),
- that their **Stripe Link card will be charged** (they approve in the Link app).

### 4. Build the Zinc order body

Save it to a file so it's identical across the calls below. `max_price` must cover box + shipping + tax; `phone_number` is the **sender's**.

```bash
cat > order.json <<'EOF'
{
  "products": [{ "url": "https://www.krispykreme.com/menu/doughnuts/all/original-glazed-doughnut", "quantity": 1 }],
  "max_price": 2000,
  "is_gift": true,
  "shipping_address": {
    "first_name": "Jane", "last_name": "Doe",
    "address_line1": "123 Market St", "address_line2": null,
    "city": "San Francisco", "state": "CA", "postal_code": "94105",
    "phone_number": "4155550123", "country": "US"
  },
  "metadata": { "source": "donuts" }
}
EOF
```

### 5. Get the Stripe payment challenge from Zinc

Post the body **once, unauthenticated**, to read the `402` challenge. Zinc validates the address first (a bad phone → `422`, fix and retry). On success you get a `402` with two `WWW-Authenticate: Payment` headers — one `method="tempo"`, one `method="stripe"`. You want the **stripe** one.

```bash
curl -s -D headers.txt -o body.json -X POST https://api.zinc.com/agent/orders \
  -H "Content-Type: application/json" --data @order.json
grep -i '^www-authenticate:.*method="stripe"' headers.txt
```

Decode the stripe challenge to get the `network_id` and confirm the amount (= `max_price` + $1):

```bash
link-cli mpp decode --challenge "$(grep -i '^www-authenticate:.*method=\"stripe\"' headers.txt | sed 's/^[Ww][Ww][Ww]-[Aa]uthenticate: //')"
```

Note the returned `network_id` and `amount` (in cents).

### 6. Create and approve a Stripe Link spend request

Pick a payment method, then create a **shared_payment_token** spend request for the decoded amount. `--context` must be ≥100 chars and is what the user sees when approving.

```bash
link-cli payment-methods list          # note the default payment method id

link-cli spend-request create \
  --credential-type shared_payment_token \
  --network-id "<network_id from step 5>" \
  --amount <amount from step 5> \
  --payment-method-id "<payment method id>" \
  --context "Sending a dozen Krispy Kreme Original Glazed doughnuts as a gift to Jane Doe in San Francisco, shipped and fulfilled by Zinc. This authorizes the donut box plus shipping, tax, and the $1 order fee."
```

This requests approval and polls. **Tell the user to open the Link app and approve within 10 minutes.** Note the returned spend request id (`lsrq_…`). (`merchant-name`/`merchant-url` are omitted on purpose — they're forbidden for SPT.)

### 7. Pay + place the order

Once approved, pay the Zinc endpoint with the SPT — `mpp pay` runs the full 402 → token → retry and places the order:

```bash
link-cli mpp pay https://api.zinc.com/agent/orders \
  --spend-request-id "<lsrq_…>" \
  --method POST \
  --data "$(cat order.json)"
```

On success this returns the created order (HTTP `201`) with an order **id** and an **`X-Api-Key`** (a `zn_live_…` token scoped to this order). Save both. The SPT is **one-time use** — if it fails, go back to step 6 for a fresh spend request.

### 8. Track the order

Poll the order with the `X-Api-Key` as a Bearer token; report tracking when it appears.

```bash
curl -s https://api.zinc.com/orders/<order_id> -H "Authorization: Bearer <X-Api-Key>"
```

Statuses: `pending` → `in_progress` → `order_placed` (terminal). Relay `tracking_numbers` when present. If the order fails, tell the user plainly what happened; Zinc handles the payment reversal automatically — **do not offer a return.**

## Safety

- **Confirm before paying.** Never create a spend request or call `mpp pay` until the user has approved item, all-in price, full address, and gift note (step 3).
- **The phone is always the sender's own, real number.** Never invent, look up, or use the recipient's phone; placeholder numbers are rejected.
- **The user approves the charge in the Link app** — you never handle their card. Surface the approval prompt clearly.
- **SPT is one-time use.** On any payment failure, create a new spend request; never reuse a consumed one.
- Reading operations (`GET /orders/{id}`, `mpp decode`) are safe.

## Notes

- **No returns.** Donuts are perishable — there is no return flow. Never offer one.
- **Fulfilled by Zinc.** Krispy Kreme fulfillment is handled through the Zinc API (`api.zinc.com`); you talk only to Zinc + `link-cli`.
- **Other payment methods:** agents with their own MPP wallet (Tempo stablecoin, x402) can pay the **same** Zinc `402` challenge directly, without Link — see the `universal-checkout` skill. This skill is the credit-card path for people who just have a card.

## Support

- Email: support@zinc.com
