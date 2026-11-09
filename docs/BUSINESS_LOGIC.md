# Business logic

- A valid market snapshot contains exactly ten valid listing prices, including the user’s own `Cancel` listings.
- `average = sum(listings) / 10`
- `net sale = average × (1 - commission)` where default commission is 20%.
- `result per item = net sale - request price`; all values are `Decimal`.
- The maximum-loss threshold is evaluated per item. Total hypothetical result is per-item result × target quantity.
- Calculation display rounds to two places only at the outer UI layer.
