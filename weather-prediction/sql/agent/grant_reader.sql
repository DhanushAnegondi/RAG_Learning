-- Not a tool. Gives the assistant's read-only role select on the marts its tools read.
-- The marts are dropped and rebuilt on every run, which drops their grants, so this runs
-- after every rebuild (warehouse.build_models) and when the assistant starts (build_agent).
-- A mart that does not exist yet is skipped. Raw tables are never granted.
do $$
declare mart text;
begin
    foreach mart in array array[
        'mart_error_by_lead', 'mart_data_quality', 'mart_verification', 'mart_scoreboard'
    ]
    loop
        if to_regclass(mart) is not null then
            execute format('grant select on %I to weatherwise_reader', mart);
        end if;
    end loop;
end
$$;
