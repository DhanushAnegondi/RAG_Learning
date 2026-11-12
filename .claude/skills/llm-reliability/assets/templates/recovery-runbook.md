# Recovery runbook: <failure>
Component: <llm | embeddings | web | index | api>
Detected by: <signal, threshold, trace field>

Symptom: <what the user or trace shows>
Impact: <degraded answers | abstentions | crash>
Automatic behavior: <retry, fallback, breaker, degrade>

## Diagnose
1. <read-only check: trace id lookup, readiness endpoint>
2. <classify: transient | permanent | parse>

## Recover
1. <bounded action, e.g. wait for breaker cooldown, rebuild index>
2. <verify: command and expected output>

## Confirm
Evidence: <command, result, trace id>
Follow-up: <test or check added so it is caught next time>
