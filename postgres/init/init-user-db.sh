#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE sonar;
    CREATE DATABASE scorecard;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "scorecard" <<-EOSQL
    CREATE TABLE IF NOT EXISTS project_scans (
        scan_id SERIAL PRIMARY KEY,
        project_name VARCHAR(255) NOT NULL,
        scan_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        final_score NUMERIC(10, 2),
        UNIQUE(project_name, scan_date)
    );

    CREATE TABLE IF NOT EXISTS scan_metadata (
        metadata_id SERIAL PRIMARY KEY,
        scan_id INTEGER NOT NULL REFERENCES project_scans(scan_id) ON DELETE CASCADE,
        metric_source VARCHAR(100) NOT NULL,
        metric_key VARCHAR(255) NOT NULL,
        metric_value VARCHAR(255),
        UNIQUE(scan_id, metric_source, metric_key)
    );

    CREATE INDEX IF NOT EXISTS idx_scan_id ON scan_metadata(scan_id);
    CREATE INDEX IF NOT EXISTS idx_project_name ON project_scans(project_name);

    CREATE TABLE IF NOT EXISTS metadata_scores (
        score_id SERIAL PRIMARY KEY,
        metadata_id INTEGER NOT NULL REFERENCES scan_metadata(metadata_id) ON DELETE CASCADE,
        score NUMERIC(10, 2) NOT NULL,
        UNIQUE(metadata_id)
    );

    CREATE INDEX IF NOT EXISTS idx_metadata_id ON metadata_scores(metadata_id);
EOSQL
