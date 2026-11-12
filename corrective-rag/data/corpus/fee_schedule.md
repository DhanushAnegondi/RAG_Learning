# Fee Schedule (synthetic)

Fees are identified by code. Quote the code on any customer-facing correction or waiver request.
Grace periods differ by product; the 15-day grace period in the servicing runbook is the personal loan
standard and also applies to HELOC accounts.

## Late payment fees
- `FEE-LATE-01` - Personal loan late fee: 5% of the past-due payment or $25, whichever is less. Assessed
  only after the 15-day grace period has passed.
- `FEE-LATE-02` - Auto loan late fee: $35 flat, assessed after a 10-day grace period.
- `FEE-LATE-03` - Credit card late fee: $32 for a first late payment, $41 if another occurs within six
  billing cycles. Card accounts also receive a 21-day interest-free window on new purchases when the
  prior balance is paid in full; this is not the same as a late-fee grace period.
- `FEE-LATE-04` - Small business loan late fee: 5% of the past-due amount, assessed after a 5-day grace period.

## Returned payment fees
- `FEE-NSF-01` - Returned payment fee on credit card accounts: $29 per returned payment.
- `FEE-NSF-02` - Returned (NSF) payment fee on installment loans: $15 per returned payment, charged at most
  once per scheduled due date.
- A returned payment fee is never charged together with a late fee for the same missed due date; the larger
  of the two applies.

## Origination, payoff, and service fees
- `FEE-ORIG-01` - Personal loan origination fee: 2% of the amount financed, deducted from proceeds.
- `FEE-ORIG-02` - Student loan refinance origination fee: none.
- `FEE-PAYOFF-02` - Payoff statement fee: the first statement each year is free, then $10 each.
- `FEE-WIRE-04` - Expedited payoff by wire: $20 per wire.
- `FEE-FX-03` - Foreign transaction fee on credit cards: 3% of the transaction amount.
- `FEE-COPY-07` - Paper statement copy: $5 per statement; electronic copies are free.

## Prepayment
- `FEE-PREPAY-00` - No prepayment penalty on personal loans, auto loans, or student loan refinances.
- `FEE-PREPAY-05` - Small business loans carry a 2% prepayment fee if paid off within the first 12 months.

## Grace period summary
| Product | Grace period before late fee |
|---|---|
| Personal loan | 15 days |
| HELOC | 15 days |
| Auto loan | 10 days |
| Credit card | 21-day interest-free window (late fee applies after the due date) |
| Small business loan | 5 days |

## Waivers
- One late fee waiver per account per 12 months may be granted by a servicing agent without approval.
- Waivers of `FEE-ORIG-01` after funding require a supervisor and a documented processing error.
