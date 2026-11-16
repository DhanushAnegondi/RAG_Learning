-- parameters: city, max_lead, days, min_days, ratio, gap. Drift check for the corrected
-- leads (1 to max_lead): this project's
-- average miss over the last `days` scored days against the held-out miss stored when the
-- methods were chosen. A live forecast is used where one exists, else the replayed one.
-- drifted = enough days, recent miss over `ratio` times the stored one and over `gap` C worse.
with scored as (
    select
        logged.city,
        logged.variable,
        logged.lead_days,
        logged.date,
        logged.kind,
        abs(
            logged.pred_c
            - case logged.variable when 'tmax' then actual.tmax_c else actual.tmin_c end
        ) as miss_c,
        row_number() over (
            partition by logged.city, logged.variable, logged.lead_days, logged.date
            order by case when logged.kind = 'live' then 0 else 1 end, logged.issued_on
        ) as pick
    from log_forecast as logged
    inner join stg_actual_daily as actual
        on logged.city = actual.city and logged.date = actual.date
    where logged.city = %(city)s and logged.lead_days <= %(max_lead)s
),

latest as (
    select
        scored.*,
        row_number() over (
            partition by scored.city, scored.variable, scored.lead_days
            order by scored.date desc
        ) as age
    from scored
    where scored.pick = 1
),

recent as (
    select
        city,
        variable,
        lead_days,
        count(*) as n_days,
        count(*) filter (where kind = 'live') as n_live,
        min(date) as first_day,
        max(date) as last_day,
        avg(miss_c) as recent_mae_c
    from latest
    where age <= %(days)s
    group by city, variable, lead_days
)

select
    recent.variable,
    recent.lead_days,
    chosen.method,
    recent.n_days,
    recent.n_live,
    recent.first_day,
    recent.last_day,
    cast(round(cast(recent.recent_mae_c as numeric), 3) as double precision) as recent_mae_c,
    chosen.test_mae_c as baseline_mae_c,
    (
        recent.n_days >= %(min_days)s
        and recent.recent_mae_c > %(ratio)s * chosen.test_mae_c
        and recent.recent_mae_c - chosen.test_mae_c > %(gap)s
    ) as drifted
from recent
inner join app_model_eval as chosen
    on
        recent.city = chosen.city
        and recent.variable = chosen.variable
        and recent.lead_days = chosen.lead_days
        and chosen.chosen
order by recent.variable, recent.lead_days;
