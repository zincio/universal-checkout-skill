---
name: send-donuts
description: Send a box of Krispy Kreme donuts (doughnuts) to someone by mail, paid by credit card via a hosted Stripe checkout, driven entirely from the terminal. Use when the user wants to send donuts, doughnuts, treats, or a thank-you gift to a lead, prospect, customer, colleague, or friend — e.g. "send donuts to Jane at Acme", "mail a dozen glazed to our new customer", "send a thank-you gift to the team". Talks only to the Send a Dozen app API (sendadozen.ai); pays per order via Stripe hosted checkout (HTTP 402); fulfilled via Zinc.
---

# Send a Dozen

Send Krispy Kreme donuts to someone by mail, paid by credit card, from the terminal. This skill drives the **Send a Dozen** app API (`https://sendadozen.ai`) — pick a box, give a recipient address, confirm, pay via a **hosted Stripe checkout link**, and track it to the door.

> **Everything here is plain HTTP + text — fully runnable with `curl` alone.** No API key, no client library, no browser automation on the happy path. Payment is a link you print for the user to open. Orders are **fulfilled via Zinc**; this skill talks only to `sendadozen.ai`, never to Zinc directly.

All amounts are in **US cents** (e.g. `4900` = $49.00). Ships to US addresses.

## How payment works (read first)

There is no account and no stored key. Each order pays for itself inline:

1. `POST /orders` with **no** `Authorization` header → the server replies **HTTP 402** with a payment challenge.
2. The challenge is in the JSON **response body** (also mirrored in `WWW-Authenticate: Payment …` headers, but you never need to parse headers — **read the body**). It carries a `payment_id` and a **Stripe `checkout_url`**.
3. **Print the `checkout_url`** and tell the user to open it and pay. **Never run `open`** — just print the URL; terminals auto-link it.
4. Poll `GET /payments/{payment_id}` every ~5s until `status` is `ready`, which returns a `credential`.
5. Retry the **same** `POST /orders` with header `Authorization: Payment <credential>` and a **byte-identical body** → **HTTP 201** with an `order_id`.

## Steps, in order

### 1. Fetch the catalog and let the user pick

```bash
curl -s https://sendadozen.ai/catalog.json
```

Returns:

```json
{
  "updated_at": "2026-07-01T00:00:00Z",
  "items": [
    { "sku": "original-glazed-dozen", "title": "Original Glazed Dozen",
      "price_cents": 1899, "all_in_estimate_cents": 4900,
      "ships_nationwide": true, "image": "https://…" }
  ]
}
```

Present the options with their **all-in prices** — use `all_in_estimate_cents` (item + shipping + tax + handling), not `price_cents`, so the user sees what they will actually pay. Only offer items with `ships_nationwide: true` unless you have confirmed the destination is served. If the user already named a SKU, accept it and skip the menu.

### 2. Gather the recipient address and the sender's phone

- **Address** — if the user supplied one, use it verbatim. Otherwise, research the recipient's **company shipping address** (HQ, or the named office) via web search and confirm it back to the user before proceeding.
- **Phone number** — this is **always the sender's own phone**, never the recipient's. It follows the Uber-Eats pattern: any delivery issue routes back to the person who sent the gift. **Never invent or look up a recipient's phone.** The sender's phone is a required input — ask for it if you don't have it.

Recipient object fields: `first_name`, `last_name`, `address_line1`, `address_line2` (nullable), `city`, `state` (2-letter), `postal_code`, `phone_number` (the sender's).

### 3. Confirm before ordering — MANDATORY

**Before any `POST /orders`, show the user all of this and wait for an explicit "yes":**

- the **item** (title) and its **all-in price** formatted as dollars (e.g. `$49.00`),
- the **full recipient address** as it will be shipped,
- the **gift note** (if any),
- a reminder that a credit card will be charged via the Stripe link.

Do not send the order until the user explicitly confirms. (This step is required even if no other checkout skill is installed — do not rely on one.)

### 4. Place the order → get the 402 challenge → print the pay link

Post the order with no auth. Save the exact body you send — you will resend it byte-for-byte after payment.

```bash
curl -s -w '\n%{http_code}\n' -X POST https://sendadozen.ai/orders \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "original-glazed-dozen",
    "recipient": {
      "first_name": "Jane",
      "last_name": "Doe",
      "address_line1": "123 Market St",
      "address_line2": null,
      "city": "San Francisco",
      "state": "CA",
      "postal_code": "94105",
      "phone_number": "5551234567"
    },
    "gift_note": "Thanks for being a great customer!",
    "public": false
  }'
```

Response is **HTTP 402** with the challenge in the body:

```json
{
  "payment_required": {
    "payment_id": "pay_abc123",
    "amount_cents": 4900,
    "methods": [
      { "type": "stripe_checkout", "checkout_url": "https://pay.sendadozen.ai/p/pay_abc123" }
    ]
  }
}
```

Read `payment_required.methods[0].checkout_url` and `amount_cents` from the body, then **print** them for the user — do not open a browser:

```
Open this link to pay $49.00: https://pay.sendadozen.ai/p/pay_abc123
```

### 5. Poll for the credential

After the user pays in their browser, poll every ~5 seconds until the payment resolves:

```bash
curl -s https://sendadozen.ai/payments/pay_abc123
```

- `{ "status": "pending" }` → keep waiting, poll again in ~5s.
- `{ "status": "ready", "credential": "cred_xyz789" }` → proceed to step 6.
- `{ "status": "expired" }` or `{ "status": "failed" }` → the link is dead / the card did not go through. Tell the user; no charge was captured and nothing shipped. Start over from step 4 to get a fresh link.

### 6. Resubmit with the credential (byte-identical body)

Retry `POST /orders` with the credential and the **exact same JSON body** from step 4:

```bash
curl -s -w '\n%{http_code}\n' -X POST https://sendadozen.ai/orders \
  -H "Content-Type: application/json" \
  -H "Authorization: Payment cred_xyz789" \
  -d '{
    "sku": "original-glazed-dozen",
    "recipient": {
      "first_name": "Jane",
      "last_name": "Doe",
      "address_line1": "123 Market St",
      "address_line2": null,
      "city": "San Francisco",
      "state": "CA",
      "postal_code": "94105",
      "phone_number": "5551234567"
    },
    "gift_note": "Thanks for being a great customer!",
    "public": false
  }'
```

On success → **HTTP 201**:

```json
{ "order_id": "ord_456", "status": "placing", "order_token": "tok_def", "poll_url": "https://sendadozen.ai/orders/ord_456" }
```

Save the `order_token` — you need it to read the order status in the next step.

### 7. Track the order to the door

Poll the order status, passing the `order_token` from step 6 as a Bearer token (the endpoint is protected because it carries the recipient's address). Report tracking to the user when it appears.

```bash
curl -s https://sendadozen.ai/orders/ord_456 \
  -H "Authorization: Bearer tok_def"
```

Returns `{ "status", "tracking?", "human_message?" }`. Status moves `placing` → `shipping` → `shipped` (or `failed`). When `tracking` is present, relay it. **If the order fails, relay `human_message` to the user verbatim** — it explains the situation (e.g. the card was not charged / the authorization was released and nothing shipped). Do not paraphrase it.

## Safety

- **Confirm before charging.** Never `POST /orders` (step 4) until the user has explicitly approved the item, all-in price, full recipient address, and gift note (step 3). This is a hard requirement, independent of any other skill.
- **Print the pay link; never run `open`.** The user pays in their own browser. Just print the `checkout_url`.
- **The phone number is always the sender's own.** It exists so delivery problems reach the sender. Never use, invent, or look up the recipient's phone.
- **Read the 402 challenge from the JSON body**, not from response headers.
- **Byte-identical resubmit.** The body in step 6 must exactly match step 4, or the credential will not apply.
- Reading operations (`GET /catalog.json`, `GET /payments/{id}`, `GET /orders/{id}`) are always safe.

## Notes

- **No returns.** Donuts are perishable — there is no return or refund-by-return flow. Never offer one. If something goes wrong, the order's `human_message` explains the resolution.
- **Fulfilled via Zinc.** Send a Dozen handles fulfillment through Zinc; you never call Zinc directly — only `sendadozen.ai` (a.k.a. `api.sendadozen.ai`).

## Support

- Email: support@zinc.com
