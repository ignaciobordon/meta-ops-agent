# Meta Ops Agent — Pricing Plans

## Plan Comparison

| Feature | TRIAL | PRO | ENTERPRISE | WHITE LABEL |
|---------|-------|-----|------------|-------------|
| **Price** | $0 (14 days) | $149/mo | Custom | Custom |
| **Ad Accounts** | 1 | 100 | Unlimited | Unlimited |
| **Decisions/month** | 50 | 1,000 | Unlimited | Unlimited |
| **Creatives/month** | 30 | 500 | Unlimited | Unlimited |
| **Execution Mode** | Dry-run only | Live + Dry-run | Live + Dry-run | Live + Dry-run |
| **Team Members** | 3 | Unlimited | Unlimited | Unlimited |
| **API Keys** | 1 | 10 | Unlimited | Unlimited |
| **Custom Branding** | - | - | Yes | Yes |
| **Custom Domain** | - | - | - | Yes |
| **Priority Support** | - | Email | Dedicated Slack | Dedicated Slack |
| **SLA** | - | 99.5% | 99.9% | 99.9% |

## Plan Details

### TRIAL (Free — 14 days)

- Full platform access in **dry-run mode** (no live changes to Meta Ads)
- 1 ad account, 50 decision drafts, 30 creative generations per month
- Ideal for evaluating the platform before committing
- Auto-expires after 14 days — upgrade to PRO to continue

### PRO ($149/month)

- Live execution enabled — approved decisions apply real changes
- Up to 100 ad accounts across multiple Meta connections
- 1,000 decisions and 500 creative generations per month
- Full team management (invite members with viewer/operator/admin roles)
- Up to 10 API keys for integrations
- Email support with 24h response SLA

### ENTERPRISE (Custom pricing)

- Unlimited ad accounts, decisions, and creatives
- Custom branding (logo, colors, company name)
- Dedicated Slack channel for support
- 99.9% uptime SLA
- Custom policy rules and approval workflows
- SSO/SAML integration (roadmap)

### WHITE LABEL (Custom pricing)

- Everything in ENTERPRISE, plus:
- Custom domain (yourbrand.com)
- Full white-label branding (remove Meta Ops Agent branding)
- Reseller API for managing sub-organizations
- Ideal for agencies and gym franchises (see GYM_OPS_BUNDLE.md)

## Billing

- All plans billed monthly via Stripe
- Card payments (Visa, Mastercard, Amex)
- Cancel anytime — access continues until end of billing period
- Past-due accounts enter **read-only mode** (no writes, no execution)
- Canceled accounts retain data for 30 days before archival

## FAQ

**Can I switch plans mid-cycle?**
Yes. Upgrading takes effect immediately. Downgrading takes effect at the next billing cycle.

**What happens when I hit a usage limit?**
New create/generate requests return HTTP 403 with a clear message. Existing data remains accessible.

**Is there an annual discount?**
Contact sales for annual pricing on PRO ($1,490/yr — 2 months free).

**Can I self-host?**
ENTERPRISE and WHITE_LABEL plans include a self-hosted deployment option (Docker + Helm).
