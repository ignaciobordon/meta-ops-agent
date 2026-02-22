# Stripe Setup Runbook

## Prerequisites

1. Stripe account (https://dashboard.stripe.com)
2. Backend `.env` file with Stripe credentials
3. Stripe CLI installed (for webhook testing)

## Step 1: Create Stripe Products & Prices

In Stripe Dashboard > Products:

### PRO Plan
- **Product name**: Meta Ops Agent PRO
- **Price**: $149.00 / month (recurring)
- **Lookup key**: `pro_monthly`
- Copy the **Price ID** (starts with `price_...`)

### Enterprise / White Label
- Create as custom quotes via Stripe Invoicing (no fixed price)

## Step 2: Configure Environment Variables

Add to `backend/.env`:

```env
STRIPE_SECRET_KEY=sk_live_...          # or sk_test_... for development
STRIPE_WEBHOOK_SECRET=whsec_...        # from Step 3
STRIPE_PRO_PRICE_ID=price_...          # from Step 1
```

## Step 3: Set Up Webhook Endpoint

### Production

In Stripe Dashboard > Developers > Webhooks:

1. Click "Add endpoint"
2. **Endpoint URL**: `https://yourdomain.com/api/billing/webhook`
3. **Events to listen for**:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
4. Copy the **Signing secret** (`whsec_...`) to your `.env`

### Local Development

Use Stripe CLI to forward events:

```bash
stripe listen --forward-to http://localhost:8000/api/billing/webhook
```

Copy the webhook signing secret from the CLI output into `.env`.

## Step 4: Configure Customer Portal

In Stripe Dashboard > Settings > Billing > Customer portal:

1. Enable "Customers can update payment methods"
2. Enable "Customers can cancel subscriptions"
3. Set cancellation policy: "Cancel at end of billing period"
4. Add your logo and branding
5. Set return URL: `https://yourdomain.com/settings`

## Step 5: Test the Flow

### 5a. Bootstrap + Trial

```bash
# Bootstrap creates a TRIAL subscription (no Stripe customer yet)
curl -X POST http://localhost:8000/api/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123","org_name":"Test Org","org_slug":"test-org","user_name":"Test User"}'
```

### 5b. Upgrade to PRO

```bash
# Login first to get access token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123"}' | jq -r .access_token)

# Create checkout session
curl -X POST http://localhost:8000/api/billing/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro"}'
# Returns {"checkout_url": "https://checkout.stripe.com/..."}
```

### 5c. Verify Subscription

```bash
curl http://localhost:8000/api/billing/status \
  -H "Authorization: Bearer $TOKEN"
# Returns plan, status, limits, usage
```

## Step 6: Webhook Event Handling

| Stripe Event | Backend Action |
|-------------|----------------|
| `checkout.session.completed` | Create/update Subscription → ACTIVE, set plan limits |
| `customer.subscription.updated` | Update status, sync period dates |
| `customer.subscription.deleted` | Set status → CANCELED |
| `invoice.payment_failed` | Set status → PAST_DUE (read-only mode) |

## Troubleshooting

### Webhook 400 errors
- Verify `STRIPE_WEBHOOK_SECRET` matches the endpoint's signing secret
- Ensure the webhook endpoint reads **raw body** (not JSON-parsed)
- Check Stripe Dashboard > Developers > Webhooks > Event log for details

### Checkout redirect fails
- Verify `STRIPE_PRO_PRICE_ID` is correct and the price is active
- Check CORS allows the Stripe checkout domain redirect

### Portal returns 404
- Ensure the org has a `stripe_customer_id` (created during checkout)
- Verify the Customer Portal is configured in Stripe Dashboard

### Subscription not updating
- Check that all 4 webhook events are selected in Stripe Dashboard
- Verify webhook signature validation is passing (check server logs)
- Test with `stripe trigger checkout.session.completed` CLI command

## Security Notes

- Never log or expose `STRIPE_SECRET_KEY`
- Webhook endpoint must verify Stripe signature before processing
- Store only `stripe_customer_id` and `stripe_subscription_id` — never card details
- All billing endpoints (except webhook) require JWT authentication
