# Project: telemetry ingestion

I implemented event_id deduplication and event-time handling for Kafka telemetry ingestion. I replayed a bounded offset range after a consumer failure. The platform team operated the Kafka cluster. The observed duplicate rate fell from 3% to 0.2% in a staging replay; no production throughput measurement is available.
