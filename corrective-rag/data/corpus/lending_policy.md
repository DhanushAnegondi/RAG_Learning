# Consumer Lending Eligibility Policy (sample)

> Sample corpus document. Replace the files in `data/corpus/` with your own material, then re-run
> `python -m crag.cli ingest`.

## Minimum eligibility
- Applicant must be at least 18 years old and a legal resident.
- Minimum FICO credit score for an unsecured personal loan is **660**.
- Maximum debt-to-income (DTI) ratio at origination is **43%**.
- Applicants with a bankruptcy discharged within the last 24 months are not eligible.

## Income verification
- W-2 employees provide the two most recent pay stubs.
- Self-employed applicants provide two years of tax returns and a year-to-date profit-and-loss statement.
- Stated income without documentation is never accepted.

## Adverse action
- If an application is declined, an adverse action notice must be sent within 30 days, citing the
  primary reasons and the credit score used.
