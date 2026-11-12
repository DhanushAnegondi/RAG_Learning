# Lakehouse migration

## Context
At Contoso the analytics platform ran on a legacy on-premise warehouse that could not scale for the
marketing team's clickstream volume. Queries on the largest tables took over an hour.

## What I did
I led the migration of 140 tables to a Delta lakehouse on cloud object storage. I defined a phased
cutover: shadow loads first, then reconciliation checks comparing row counts and column checksums, then
switching consumers one team at a time. I built the Terraform modules for the storage and compute
environments.

## Result
The largest clickstream queries fell from over an hour to under four minutes. We decommissioned the
legacy warehouse nine weeks after the first shadow load.
