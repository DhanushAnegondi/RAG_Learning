-- parameters: city
select
    source,
    reason,
    count(*) as rejected_rows,
    min(seen_at) as first_seen,
    max(seen_at) as last_seen
from stg_quality_issues
where city = %(city)s
group by source, reason
order by source, reason;
