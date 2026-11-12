## Example 1
We had a nightly job that kept missing its window. I traced it to one skewed join, rewrote the key
so the work spread evenly, and the run dropped from three hours to forty minutes. Nothing clever, just
reading the query plan properly.

## Example 2
I like owning a pipeline end to end: the contract with the source team, the tests, and the alert that
wakes me up when it breaks. If it pages someone at night, I want it to be me, and I want it to be rare.
