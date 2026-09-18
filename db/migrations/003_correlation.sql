-- 003: end-to-end correlation id on jobs (API -> queue -> worker -> AI/EHR).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS correlation_id TEXT;
UPDATE jobs SET correlation_id = 'legacy-' || id WHERE correlation_id IS NULL;
