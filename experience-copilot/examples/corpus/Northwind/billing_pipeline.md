# Billing pipeline

## Problem
At Northwind the invoicing team reconciled customer invoices by hand every month-end. Invoice data
arrived from three regional systems in different formats and the close took six working days.

## What I built
I designed an Airflow-orchestrated billing pipeline that ingested the three regional exports into a
Spark staging layer, normalised currency and tax fields, and published a single invoice fact table.
I wrote idempotent loads keyed on invoice number so a rerun never double-counted revenue.

## Impact
The month-end close dropped from six working days to two. Reconciliation mismatches fell by 80 percent
in the first quarter, and finance stopped maintaining their spreadsheet macros.
