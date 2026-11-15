---
name: apiv-method
description: "Run changes through Align, Plan, Implement, Verify, Learn at a proportional tier (Low/Standard/High). Use when starting a feature, a rewrite, or resuming work."
---

# APIV method

Read [workflow policy](references/workflow-policy.md) first: tiers, precedence, evidence validity. Record `Tier: <Low|Standard|High> - <reason>` before implementing.

## The loop

1. **Align.** Read existing context (CLAUDE.md, spec, code) before asking. Ask only consequential, unresolved questions, one at a time.
2. **Plan.** Compare approaches only where the answer changes a decision. Write acceptance criteria that name a command or a measurable outcome. High tier: tracked spec plus dependency-ordered tickets.
3. **Implement.** Smallest complete slice, bounded paths. Builder and reviewer are different agents for High work.
4. **Verify.** Run checks that can detect the plausible defect. Apply the `verification-gate` skill before any claim.
5. **Learn.** Record findings, limits and the next action. A repeated defect earns a targeted check or a design fix.

## Resources

- [Workflow policy](references/workflow-policy.md): tiers, evidence rules, capture selection.
- Templates: [spec](assets/templates/spec.md), [ticket](assets/templates/ticket.md), [handoff](assets/templates/handoff.md). Omit irrelevant sections with a reason; do not fabricate work.

## AI-engineering notes

- A change that alters retrieval, grading, prompts or models is High: it needs an eval run, not only unit tests.
- Offline tests (fakes at the client boundary) gate every ticket; live eval gates metric claims.
