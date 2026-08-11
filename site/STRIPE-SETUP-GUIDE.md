# Stripe Integration Guide for 60 Minute Sites

This guide walks you through setting up Stripe payment processing for 60 Minute Sites.

## Overview

**Pricing Structure:**
- Setup Fee: $100 (one-time)
- Monthly Hosting: $50/month (recurring)

## Step 1: Create a Stripe Account

1. Go to [stripe.com](https://stripe.com) and create an account
2. Complete the business verification process
3. Make sure to enable "Test mode" while setting up

## Step 2: Create Products in Stripe

### Product 1: Setup Fee

1. Go to **Products** in your Stripe Dashboard
2. Click **Add product**
3. Fill in:
   - **Name:** Website Setup Fee
   - **Description:** One-time setup fee including template customization, 1-hour onboarding call, content integration, and domain connection.
   - **Pricing:** $100 (One time)
4. Click **Save product**

### Product 2: Monthly Hosting

1. Click **Add product**
2. Fill in:
   - **Name:** Monthly Website Hosting
   - **Description:** Monthly hosting fee including fast reliable hosting, SSL certificate, maintenance, security updates, and email support.
   - **Pricing:** $50 (Recurring - Monthly)
3. Click **Save product**

## Step 3: Create Payment Links

Stripe Payment Links are the easiest way to accept payments without writing code.

### Setup Fee Payment Link

1. Go to **Payment links** in your Stripe Dashboard
2. Click **Create payment link**
3. Select the "Website Setup Fee" product
4. Customize the payment page:
   - Add your logo
   - Customize confirmation page message
5. Click **Create link**
6. Copy the URL (e.g., `https://buy.stripe.com/xxxxx`)

### Monthly Hosting Payment Link

1. Click **Create payment link**
2. Select the "Monthly Website Hosting" product
3. This will create a subscription checkout
4. Customize as needed
5. Click **Create link**
6. Copy the URL

## Step 4: Add Payment Links to Your Website

Replace the "Get Started" buttons on your pricing page with the Stripe payment links.

### Example HTML:

```html
<!-- Setup Fee Button -->
<a href="https://buy.stripe.com/YOUR_SETUP_LINK" class="btn btn-primary btn-lg" target="_blank">
  Pay Setup Fee - $100
</a>

<!-- Monthly Subscription Button -->
<a href="https://buy.stripe.com/YOUR_MONTHLY_LINK" class="btn btn-primary btn-lg" target="_blank">
  Start Monthly Plan - $50/mo
</a>
```

## Step 5: Create a Combined Checkout (Optional)

For a better customer experience, create a combined payment link:

1. Go to **Payment links**
2. Click **Create payment link**
3. Add BOTH products:
   - Website Setup Fee ($100 one-time)
   - Monthly Website Hosting ($50/month recurring)
4. The customer will pay $150 upfront ($100 + first month)
5. They'll be automatically billed $50/month thereafter

## Step 6: Set Up Webhook Notifications (Optional)

To get notified of successful payments:

1. Go to **Developers > Webhooks**
2. Click **Add endpoint**
3. Enter your endpoint URL (or use a service like Zapier)
4. Select events:
   - `checkout.session.completed`
   - `invoice.paid`
   - `customer.subscription.created`

## Step 7: Go Live

When you're ready to accept real payments:

1. Go to **Developers > API keys**
2. Toggle off "Test mode"
3. Update your payment links to use live mode
4. Test a real transaction with a small amount

## Stripe Dashboard Links

- **Dashboard:** https://dashboard.stripe.com
- **Products:** https://dashboard.stripe.com/products
- **Payment Links:** https://dashboard.stripe.com/payment-links
- **Customers:** https://dashboard.stripe.com/customers
- **Webhooks:** https://dashboard.stripe.com/webhooks

## Customer Portal

Set up the customer portal so customers can:
- Update payment methods
- View invoice history
- Cancel subscriptions

1. Go to **Settings > Billing > Customer portal**
2. Configure allowed actions
3. Add portal link to your website for existing customers

## Best Practices

1. **Always test first** - Use Stripe's test mode and test card numbers
2. **Send receipts** - Enable automatic receipt emails in Stripe settings
3. **Set up dunning** - Configure retry logic for failed payments
4. **Keep records** - Stripe provides excellent reporting and exports

## Test Card Numbers

Use these in test mode:
- **Success:** 4242 4242 4242 4242
- **Decline:** 4000 0000 0000 0002
- **Requires auth:** 4000 0025 0000 3155

Any future date for expiry, any 3 digits for CVC.

## Support

- Stripe Support: https://support.stripe.com
- Stripe Documentation: https://stripe.com/docs

---

Remember to replace all test payment links with live links before launching!
