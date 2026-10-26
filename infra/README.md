# FreightLens on AWS (Terraform)

One `terraform apply` builds the whole stack; one `terraform destroy` removes it.

```
internet --HTTP:80--> ALB --3000--> ECS Fargate task [ web :3000 + api :8000 ] --5432--> RDS Postgres 16
                                                                |
                                                                +--> S3 (uploads)   Secrets Manager (secrets)
```

| File | What it creates |
| --- | --- |
| `versions.tf` | Terraform and provider versions, region, default tags |
| `variables.tf` | The few knobs: region, desired_count, image tag, CPU architecture |
| `network.tf` | Default VPC lookup, three chained security groups (ALB, task, database) |
| `storage.tf` | Two ECR repositories (images) and the private, encrypted uploads bucket |
| `secrets.tf` | JWT secret, app-role password, an empty OpenAI-key secret |
| `database.tf` | RDS Postgres (private, encrypted, password managed by RDS) |
| `iam.tf` | Execution role (pull images, read secrets) and task role (uploads bucket only) |
| `alb.tf` | Load balancer, target group, HTTP listener |
| `ecs.tf` | Cluster, logs, app task (web + api), one-off bootstrap task, service |
| `outputs.tf` | The URL and the ready-made commands used below |

## Cost

About $0.09 per hour while it is up (load balancer, one Fargate task, one small database). Destroy it when
you finish testing. Left running for a month it would be roughly $65.

## Deploy

Run everything from this `infra/` folder. Your AWS CLI must already work (`aws sts get-caller-identity`).

### 1. Create the infrastructure (no app running yet)

```
terraform init
terraform validate
terraform plan
terraform apply
```

`desired_count` defaults to 0, so the service exists but starts nothing. The database takes about 5-10 minutes.

### 2. Build and push the images

Docker must be running. `--platform linux/arm64` matches the ARM64 task (Apple Silicon builds ARM natively).

```
REGISTRY=$(terraform output -raw ecr_registry)
API_REPO=$(terraform output -raw ecr_api_repository)
WEB_REPO=$(terraform output -raw ecr_web_repository)

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $REGISTRY

docker build --platform linux/arm64 -t $API_REPO:latest ..
docker build --platform linux/arm64 -t $WEB_REPO:latest ../web

docker push $API_REPO:latest
docker push $WEB_REPO:latest
```

(Change `us-east-1` if you changed the `region` variable.)

### 3. Prepare the empty database

```
eval "$(terraform output -raw run_bootstrap_command)"
```

Watch it finish (about 1-2 minutes):

```
aws logs tail /ecs/freightlens --region us-east-1 --since 10m
```

You want to see `the database is ready`. Run it again any time; it is safe to repeat.

### 4. Store the OpenAI key (from your own terminal, never in chat or in a file in git)

Your key is already in the repo's `.env`. This copies it straight into Secrets Manager without printing it:

```
aws secretsmanager put-secret-value --region us-east-1 \
  --secret-id freightlens/openai-api-key \
  --secret-string "$(grep '^OPENAI_API_KEY=' ../.env | cut -d= -f2-)"
```

### 5. Start the app

```
terraform apply -var desired_count=1
```

Wait 2-3 minutes, then:

```
terraform output app_url
```

Open that address. Sign up, upload a quote and an invoice, run a comparison.

### Watching and updating

```
eval "$(terraform output -raw logs_command)"        # follow the logs
eval "$(terraform output -raw redeploy_command)"    # restart on newly pushed images
```

## Destroy

```
terraform destroy
```

Then check nothing is left:

```
aws rds describe-db-instances --region us-east-1 --query 'DBInstances[].DBInstanceIdentifier'
aws elbv2 describe-load-balancers --region us-east-1 --query 'LoadBalancers[].LoadBalancerName'
aws ecs list-clusters --region us-east-1
aws s3 ls | grep freightlens
```

## Honest limits (what a production version would change)

- HTTP only. Production: a domain, an HTTPS listener with a certificate, port 80 redirecting to it.
- Default VPC, public subnets, and a public IP on the task (a NAT gateway costs about $32 a month). Only the load
  balancer can reach the task, but private subnets would be better.
- Terraform state is a local file and contains the generated secrets. Production: an encrypted S3 backend with locking.
- The database has no backups, no standby and no deletion protection, so that destroy is fast.
- The background pipeline runs inside the API process. Production: a queue and separate workers.
- No alarms or deploy pipeline yet (CloudWatch alarms and a GitHub Actions deploy with OIDC are the next steps).
