-- Add h2h_data JSON column to predictions table
-- Run on production: psql -U pattern_user -d pattern_interruption -f migrations/add_h2h_data_column.sql

ALTER TABLE predictions ADD COLUMN IF NOT EXISTS h2h_data JSON;
