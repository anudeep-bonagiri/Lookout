-- Tiger Data schema. Applied only when TimescaleDB is present.
-- Users and contacts stay ordinary tables. These three are hypertables.

CREATE EXTENSION IF NOT EXISTS timescaledb;

SELECT create_hypertable('payment_attempts', 'created_at', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('risk_checks', 'created_at', if_not_exists => TRUE, migrate_data => TRUE);
SELECT create_hypertable('vitals_samples', 'created_at', if_not_exists => TRUE, migrate_data => TRUE);

CREATE MATERIALIZED VIEW IF NOT EXISTS attempts_hourly
WITH (timescaledb.continuous) AS
SELECT
  time_bucket(INTERVAL '1 hour', created_at) AS bucket,
  user_id,
  COUNT(*) AS attempts,
  COUNT(*) FILTER (WHERE outcome = 'hold') AS holds
FROM payment_attempts
GROUP BY 1, 2
WITH NO DATA;

ALTER MATERIALIZED VIEW attempts_hourly SET (timescaledb.materialized_only = false);

SELECT add_continuous_aggregate_policy(
  'attempts_hourly',
  start_offset => INTERVAL '30 days',
  end_offset => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists => TRUE
);
