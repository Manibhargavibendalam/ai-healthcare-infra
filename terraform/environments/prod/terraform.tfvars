# Prod-like values: same modules, bigger counts, protection on.
# Secrets intentionally absent: TF_VAR_db_password / TF_VAR_redis_auth_token.
env                    = "prod-like"
api_count              = 2
worker_count           = 2
redis_nodes            = 2
db_deletion_protection = true
skip_final_snapshot    = false
