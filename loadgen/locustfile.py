"""Load shapes for the assessment (run headless in the loadgen container):
  1. normal workload      -> NormalUser browsing + occasional jobs
  2. increased API load   -> ApiHeavy reads/bookings
  3. increased background -> JobPoster flooding the queue
  4. burst                -> BurstUser, zero wait (combine with -u 100 -r 20)
Run: docker compose --profile loadgen run --rm locust --headless
       -u 20 -r 5 --run-time 2m --host http://nginx:8080
"""
from locust import HttpUser, between, constant, task


class NormalUser(HttpUser):
    weight = 4
    wait_time = between(0.5, 2.0)

    @task(3)
    def health(self):
        self.client.get("/health")

    @task(2)
    def browse(self):
        self.client.get("/api/v1/patients")
        self.client.get("/api/v1/doctors")

    @task(1)
    def queue(self):
        self.client.get("/api/v1/queue/stats")


class ApiHeavy(HttpUser):
    weight = 2
    wait_time = between(0.1, 0.5)

    @task(2)
    def read(self):
        self.client.get("/api/v1/appointments")

    @task(1)
    def book(self):
        self.client.post("/api/v1/appointments",
                         json={"patient_id": 1, "doctor_id": 1,
                               "scheduled_at": "2026-11-01T10:00:00"})


class JobPoster(HttpUser):
    weight = 2
    wait_time = between(0.2, 0.8)

    @task
    def post_job(self):
        self.client.post("/api/v1/jobs", json={"type": "load", "patient_id": 1})


class BurstUser(HttpUser):
    weight = 1
    wait_time = constant(0)

    @task
    def burst(self):
        self.client.post("/api/v1/jobs", json={"type": "burst", "patient_id": 2})
