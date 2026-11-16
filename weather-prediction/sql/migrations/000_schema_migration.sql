-- Bookkeeping for the migration runner (warehouse.migrate). Safe to run on every start.
create table if not exists schema_migration (
    name text primary key,
    applied_at timestamp not null default localtimestamp
);
