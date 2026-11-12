# Corpus (synthetic)

Every document here is fictional and written for evaluating a retrieval-augmented generation pipeline.
The lender does not exist, and none of these figures are legal, financial, or lending advice.

The first three files are the original sample documents. The rest were added so that retrieval has to
choose among dozens of chunks, with deliberate distractors (similar numbers for different products) and
exact identifiers (fee codes, form numbers, state codes).

| File | Content |
|---|---|
| `lending_policy.md` | Eligibility, income verification, adverse action (original) |
| `loan_products.md` | Personal, auto, and HELOC product terms (original) |
| `servicing_runbook.md` | Payment posting, delinquency stages, hardship (original) |
| `fee_schedule.md` | Fee codes and grace periods by product |
| `state_addenda.md` | State-specific caps and rules by state code |
| `credit_card_terms.md` | Card rates, fees, grace period, rewards |
| `student_loan_refi.md` | Student loan refinance terms |
| `small_business_loans.md` | Small business term loans |
| `hardship_and_collections.md` | Hardship programs, contact rules, settlements |
| `fraud_and_identity.md` | Identity verification and fraud claims |
| `glossary.md` | Acronym definitions |
| `forms_and_disclosures.md` | Form codes and retention |

The evaluation set in `eval/eval_set.jsonl` quotes short verbatim snippets from these files as evidence.
Edit a document and the matching evidence strings must be updated too.
