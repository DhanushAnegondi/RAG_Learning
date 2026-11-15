# Sprint 04 review

Two independent reviewers (separate agents, read-only, loaded with `ledger/reviewer-brief.md`
and the ponytail-review method). Both returned FAIL. Each finding below is fixed, or recorded
with the reason it was left.

## Code review: FAIL (21 findings)

| # | Kind | Finding | Outcome |
|---|---|---|---|
| 1 | BUG | A failed tool step could leave a conversation unusable: a tool call with no result stays in the thread, and the model API rejects every later request | Fixed. A bug inside a tool becomes an error result; a failure of the log itself is caught in the graph; a new question first finishes a cut-off run; the step limit is set above the model-call limit so the call limit always stops first. Tests added |
| 2 | BUG | The number check accepted almost any small whole number: the month and day of every date counted as free numbers, and a whole number matched any value within 0.5 | Fixed. Date parts support only a date written out ("Nov 15"); a whole number must match exactly. The prompt now asks for numbers exactly as returned |
| 3 | BUG | The tool description told the model about "12 months", "3 C" and "since 2022", which the check would then reject | Fixed. Those statements are returned with the rows as `facts`, so they are sources; "since 2022" removed (the result carries `n_days`) |
| 4 | BUG | Stop reasons unhandled: a refusal gave an empty answer marked as checked; a cut-off reply was shown as final | Fixed. Refusal, cut-off and empty replies become a stated error with a fixed message; the unusable reply is dropped. Tests added |
| 5 | BUG | Resuming an unknown thread raised KeyError | Fixed: `LookupError("no such conversation")`. Test added |
| 6 | RISK | Weekdays were never grounded: the model had to work out which date "Saturday" is | Fixed. `get_outlook` returns `weekday`; the prompt gives today's weekday and forbids deriving one |
| 7 | RISK | Replay ignored what the call was: a reused call id returned the old rows. Concurrent questions on one thread interleave | Fixed. Stored tool and arguments must match or the call is refused; one question at a time per thread (in-process lock). Not fixed: two server processes sharing a thread |
| 8 | BUG | `.env` parsing: a Notepad BOM hid the first key, `export KEY=` and `KEY=v # note` were mis-read, an empty existing variable blocked the file | Fixed, with a test |
| 9 | BUG | `mutation_check.py` could leave a mutated migration on disk if the database was unreachable | Fixed: the schema drop is inside the `try` |
| 10 | BUG | The page said "numbers checked against the data" for an outage or the call limit; a 422 showed "[object Object]"; the page appended text to the stored question | Fixed in `web/app.js` |
| 11 | RISK | A bad key or model name looked like a passing outage | Fixed. HTTP 400/401/403/404 from the model give a setup message; the reason goes to the server log, never to the user |
| 12 | BUG | Remembering "85 F" stored "29.4 C (84.9 F)" | Fixed: the user's number is kept, the other unit is added ("85 F (29.4 C)") |
| 13 | RISK | Any thread id can be read by anyone who can reach the site; reading history needs the API key | Thread id length capped. Access control not added: one local user, site bound to 127.0.0.1. Listed under limits |
| 14 | NIT | Migration comment named a file that does not exist | Fixed |
| 15 | NIT | No read-only setting on the tool transaction | Fixed: `set local transaction_read_only = on` |
| 16 | NIT | Empty exception message raised IndexError | Fixed |
| 17 | NIT | `WEATHERWISE_FALLBACKS` accepted any string | Fixed: on, or `off` |
| 18 | NIT | A failed `build_agent` leaked its pool | Fixed |
| 19 | NIT | History is never trimmed, so a very long thread can overflow the model's context before the call limit | Not fixed. Sprint 05 |
| 20 | NIT | `max_model_calls=0` fell through to the default | Fixed |
| 21 | NIT | The number check ignores the sign | Not fixed; stated in `grounding.py` and under limits |

## Test review: FAIL (19 findings)

All 40 mutants of the first list were judged killed. The findings were gaps:

| # | Kind | Finding | Outcome |
|---|---|---|---|
| 1 | SURVIVING-MUTANT | No row with a missing value: without the `None` guard the unit conversion would crash on days 8-30 | Fixed: seed has a day with no published value and no low; test and mutant added |
| 2 | WRONG-EXPECTATION | Fahrenheit twins asserted for two columns only | Fixed: bias, errors, scoreboard, low side and published low asserted |
| 3 | WEAK-TEST | Every seeded error was positive, so bias equalled average miss | Fixed: errors are now +1, +2, +3, -4 (bias 0.5, average miss 2.5) |
| 4 | UNTESTED | Stop reasons | Fixed with the code (four cases) |
| 5 | UNTESTED | Replies given as a list of blocks | Fixed: test with a thinking block and a text block |
| 6 | WEAK-TEST | Day-of-month digits passed the number check | Fixed with the code; tests pin the new rule |
| 7 | UNTESTED | Tool arguments and preferences as sources, through the graph | Fixed: test and two mutants |
| 8 | UNTESTED | Preference validation (thresholds, home city) | Fixed |
| 9 | SURVIVING-MUTANT | A preference written under the wrong user | Fixed: test and mutant |
| 10 | UNTESTED | `facts` and the row cap | Fixed |
| 11 | UNTESTED | Only the latest question's tool calls reported; unknown thread | Fixed |
| 12 | UNTESTED | Recovery after a model failure; the site's failure path | Fixed |
| 13 | UNTESTED | `load_env` | Fixed |
| 14 | UNTESTED | Starting before any mart exists | Fixed: test and mutant |
| 15 | SURVIVING-MUTANT | `kind = 'live'` in the outlook query | Fixed: a replay issued the same day is seeded; mutant added |
| 16 | WEAK-TEST | Argument bounds tested at 99 only; loose error-text matches | Fixed: 0, 31 and exact messages |
| 17 | WEAK-TEST | The refusal was only checked for one number | Fixed: asserts it contains no digit and the draft is not in history |
| 18 | WEAK-TEST | "Lost connection" is simulated by raising the error, not by killing a backend | Not fixed. Recorded in `tests/CATALOG.md` |
| 19 | SURVIVING-MUTANT | `durability="sync"` cannot be killed by an in-process test | Not a test: proven by `scripts/prove_resume.py` (a real kill), `run/resume.out` |

Also noted by the reviewer and accepted as limits: the scripted model ignores `bind_tools`
(the tool definitions are now asserted directly instead), and the in-process crash test unwinds
normally where a real kill does not (the proof script covers the real kill).

## Mutation run

`run/mutation.out`: the mutants of the sprint-04 files only (agent code, agent SQL, the agent
migration, `config.py`). The 79 mutants of sprints 01-03 were last run in sprint 03
(`results/sprint-03/run/mutation.out`) and were not rerun: the machine was short of memory and
each test process took minutes to start. Shared files those mutants touch changed in two
places this sprint (`warehouse.build_models` now grants the reader role; `site.py` gained the
agent endpoints); the full suite, which contains their killing tests, passes (`run/green.out`).

## After the reviews: what the live run showed

Five questions were put to Claude on the real database (`run/live.out`).

- The first answer attached "last 12 months" to the published forecast's figures, which cover
  the whole stored history. Not a number error, so the check passed it. Fixed at the source:
  the tool now states which columns cover which period; the fifth question confirms the model
  then described both periods correctly.
- A question about a date past the 30-day outlook was refused (a number in no tool result).
  A date the user wrote out ("December 25") was not counted as a source; it is now, with a test.
- Not fixed, recorded as a limit: one answer stated a 0.5 F gap the model had subtracted
  itself; it passed because 0.5 appears elsewhere in the same result.
- The key had been saved into the tracked `.env.example`. It was moved to the git-ignored
  `.env` and the example restored before anything was committed.
