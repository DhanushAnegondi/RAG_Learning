# Data quality program

## Motivation
Late in my first year at Northwind a currency bug sent wrong totals to the executive dashboard for two
days. Nobody noticed until a regional manager complained.

## Approach
I introduced schema contracts with the source teams and added dbt tests for uniqueness, null rates and
referential integrity on the invoice tables. Failing tests blocked publication and posted to the on-call
Slack channel with the failing sample rows attached.

## Outcome
Incidents reaching the dashboard dropped from roughly one a month to none over the following two
quarters. Source teams began fixing contract breaks themselves because the alert named the field.
