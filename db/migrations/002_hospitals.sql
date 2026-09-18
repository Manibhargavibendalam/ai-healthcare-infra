-- 002: hospitals + doctor affiliation. Synthetic data only.
CREATE TABLE IF NOT EXISTS hospitals (
  id         SERIAL PRIMARY KEY,
  name       TEXT NOT NULL,
  city       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE doctors ADD COLUMN IF NOT EXISTS hospital_id INTEGER REFERENCES hospitals(id);

INSERT INTO hospitals (id, name, city) VALUES
  (1, 'Test General Hospital', 'Hyderabad'),
  (2, 'Test City Clinic', 'Secunderabad'),
  (3, 'Test Riverside Care', 'Vijayawada')
ON CONFLICT (id) DO NOTHING;

UPDATE doctors SET hospital_id = id WHERE hospital_id IS NULL AND id <= 3;

SELECT setval('hospitals_id_seq', (SELECT max(id) FROM hospitals));
