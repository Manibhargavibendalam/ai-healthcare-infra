output "alb_sg_id" {
  value = aws_security_group.alb.id
}

output "ecs_sg_id" {
  value = aws_security_group.ecs.id
}

output "db_sg_id" {
  value = aws_security_group.db.id
}

output "redis_sg_id" {
  value = aws_security_group.redis.id
}

output "exec_role_arn" {
  value = aws_iam_role.ecs_exec.arn
}

output "task_role_arn" {
  value = aws_iam_role.ecs_task.arn
}

output "app_secret_arn" {
  value = aws_secretsmanager_secret.app.arn
}
