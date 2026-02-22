# Gym Ops Bundle — White-Label for Gym Operators

## Overview

The **Gym Ops Bundle** is a white-label configuration of Meta Ops Agent designed specifically for gym franchises and fitness marketing agencies. It provides autonomous Meta Ads management tailored to the fitness industry.

## Target Customers

- **Gym franchises** (5-200 locations) running Meta Ads for local lead generation
- **Fitness marketing agencies** managing ads for multiple gym clients
- **Gym software platforms** wanting to embed ad management into their SaaS

## Bundle Configuration

| Setting | Value |
|---------|-------|
| Plan | WHITE_LABEL |
| Custom domain | `ads.yourgym.com` |
| Branding | Gym's logo + brand colors |
| Ad accounts | 1 per location |
| Decision templates | Gym-specific (budget, audience, creative rotation) |
| Policy rules | Fitness compliance (no medical claims, age restrictions) |

## Pre-Built Features

### 1. Gym-Specific Angle Library
Pre-loaded creative angles for fitness:
- New Year Resolution campaigns
- Summer body challenges
- Free trial / first-visit offers
- Transformation testimonials
- Class-specific promos (CrossFit, yoga, HIIT)

### 2. Saturation Detection
Monitors creative fatigue across locations:
- Alert when an ad creative is shown >3x frequency
- Auto-suggest rotation based on angle saturation scores
- Per-location saturation dashboards

### 3. Budget Optimization Decisions
Automated decision packs for:
- Increase budget on high-performing ad sets
- Pause underperforming audiences
- Reallocate spend between locations
- Seasonal budget adjustments

### 4. Compliance Policies
Built-in policy rules for fitness advertising:
- No "before/after" claims without disclaimers
- Age-restricted targeting (18+ only)
- Maximum daily spend caps per location
- Mandatory approval for budget increases >20%

## Pricing

- **Per-location pricing**: $29/location/month (min 5 locations)
- **Agency pricing**: $199/month base + $19/location
- **Volume discount**: 50+ locations = custom pricing

## Onboarding Flow

1. Agency signs up → WHITE_LABEL org created
2. Configure branding (logo, colors, domain)
3. Connect Meta Business Manager
4. Import location list (CSV) → creates ad accounts
5. Load gym angle library
6. Set compliance policies
7. Enable dry-run mode for 7-day validation
8. Go live with human-in-the-loop approval

## Integration Points

- **Gym CRM**: Webhook on decision execution → update CRM pipeline
- **Reporting**: API key for pulling KPI data into external dashboards
- **Slack/Teams**: Decision approval notifications
