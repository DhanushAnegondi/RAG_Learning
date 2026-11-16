-- parameters: city. The method in use per variable and lead, from the last accepted selection.
select
    variable,
    lead_days,
    method
from app_model_eval
where city = %(city)s and chosen
order by variable, lead_days;
