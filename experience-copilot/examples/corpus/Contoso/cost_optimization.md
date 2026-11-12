# Cloud cost optimization

## Problem
Within a quarter of the lakehouse going live, Contoso's cloud compute bill was 40 percent above forecast,
mostly from always-on clusters and unpartitioned scans.

## Actions
I added auto-termination for idle clusters, partitioned the three largest tables by event date, and
compacted small files nightly. I published a weekly cost dashboard broken down by team so owners could see
their own spend.

## Impact
Monthly compute spend fell by 35 percent without slowing any scheduled job, bringing the bill back under
the forecast.
