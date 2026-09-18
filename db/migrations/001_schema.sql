-- 001: base schema + synthetic seed. ALL DATA BELOW IS FAKE.
-- Idempotent: safe to apply via initdb.d on fresh volumes AND via
-- scripts/migrate.sh on live databases (IF NOT EXISTS / ON CONFLICT).
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS patients (
  id         SERIAL PRIMARY KEY,
  first_name TEXT NOT NULL,
  last_name  TEXT NOT NULL,
  dob        DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doctors (
  id         SERIAL PRIMARY KEY,
  first_name TEXT NOT NULL,
  last_name  TEXT NOT NULL,
  specialty  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
  id           SERIAL PRIMARY KEY,
  patient_id   INTEGER NOT NULL REFERENCES patients(id),
  doctor_id    INTEGER NOT NULL REFERENCES doctors(id),
  scheduled_at TIMESTAMPTZ NOT NULL,
  status       TEXT NOT NULL DEFAULT 'scheduled'
);

-- Job lifecycle: queued -> processing -> completed | failed.
-- Retries go back to 'queued' with attempts+1 and the last error kept.
CREATE TABLE IF NOT EXISTS jobs (
  id            SERIAL PRIMARY KEY,
  type          TEXT NOT NULL,
  patient_id    INTEGER REFERENCES patients(id),
  status        TEXT NOT NULL DEFAULT 'queued',
  attempts      INTEGER NOT NULL DEFAULT 0,
  max_attempts  INTEGER NOT NULL DEFAULT 3,
  payload       JSONB NOT NULL DEFAULT '{}',
  result        JSONB,
  error         TEXT,
  processing_ms INTEGER,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per EHR call attempt (audit trail for retries/failures).
CREATE TABLE IF NOT EXISTS ehr_syncs (
  id          SERIAL PRIMARY KEY,
  job_id      INTEGER NOT NULL REFERENCES jobs(id),
  mode        TEXT NOT NULL,
  status_code INTEGER,
  latency_ms  INTEGER,
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Synthetic seed, explicit ids so re-application is a no-op.
INSERT INTO doctors (id, first_name, last_name, specialty) VALUES
  (1, 'Test', 'Doctor-01', 'cardiology'),
  (2, 'Test', 'Doctor-02', 'neurology'),
  (3, 'Test', 'Doctor-03', 'general')
ON CONFLICT (id) DO NOTHING;

INSERT INTO patients (id, first_name, last_name, dob) VALUES
  (1, 'Test', 'Patient-01', '1990-01-11'),
  (2, 'Test', 'Patient-02', '1985-05-23'),
  (3, 'Test', 'Patient-03', '2000-09-02'),
  (4, 'Test', 'Patient-04', '1978-12-30'),
  (5, 'Test', 'Patient-05', '2010-03-15')
ON CONFLICT (id) DO NOTHING;

INSERT INTO appointments (id, patient_id, doctor_id, scheduled_at) VALUES
  (1, 1, 1, now() + interval '1 day'),
  (2, 2, 3, now() + interval '2 days'),
  (3, 3, 2, now() + interval '3 days')
ON CONFLICT (id) DO NOTHING;

SELECT setval('doctors_id_seq', (SELECT max(id) FROM doctors));
SELECT setval('patients_id_seq', (SELECT max(id) FROM patients));
SELECT setval('appointments_id_seq', (SELECT max(id) FROM appointments));
