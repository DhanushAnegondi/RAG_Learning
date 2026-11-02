# Project: loan reconciliation

I implemented Snowflake SQL reconciliation between loan-servicing extracts and reporting tables, using loan_id and business_date as the comparison key. I added null-key quarantine and reconciled row counts and principal totals. In the documented UAT sample, mismatches fell from 120 rows to 8 rows. I did not own the entire data warehouse.
