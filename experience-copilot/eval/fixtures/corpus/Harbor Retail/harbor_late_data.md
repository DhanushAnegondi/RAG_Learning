# Project: late sales corrections

I implemented a daily correction merge for late sales records keyed by sale_id at Harbor Retail. The merge compared source_updated_at and retained the newest version. The analytics team selected the reporting cutoff. I tested a sale arriving two days late and a corrected sale arriving out of order. No streaming system was involved.
