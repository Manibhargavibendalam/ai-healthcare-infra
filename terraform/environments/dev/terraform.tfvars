# Dev values: smallest sizes, protection off. Same STRUCTURE as prod.
# Secrets intentionally absent: TF_VAR_db_password / TF_VAR_redis_auth_token.
env                    = "dev"
api_count              = 1
worker_count           = 1
redis_nodes            = 1
db_deletion_protection = false
skip_final_snapshot    = true
