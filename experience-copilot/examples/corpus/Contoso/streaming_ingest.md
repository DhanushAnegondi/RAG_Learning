# Streaming ingestion

## Design
For Contoso's web events I built a Kafka to Spark Structured Streaming job that wrote micro-batches into
the lakehouse every minute, with exactly-once semantics through checkpointed offsets.

## Operations
I set up lag alerts and a dead-letter topic for malformed events. When a producer shipped a breaking
schema change, the dead-letter topic isolated the bad records and the main stream kept flowing.
