# Agent Engineer Opinions FastMCP Server

This project exposes `agent_engineer_opinions.csv` as a FastMCP server, deployed on AWS Lambda as a container image.

## Endpoints

- MCP: `POST /mcp`
- Health: `GET /health`
- Service info: `GET /`

## MCP tools

- `data_catalog()`
- `sample_opinions(subject, limit=7)`
- `subject_stats(subject)`
- `summarize_subject(subject)`

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Then open:
- `http://127.0.0.1:8000/health`
- MCP endpoint at `http://127.0.0.1:8000/mcp`

## AWS deployment (container Lambda)

1. Authenticate AWS CLI and set shell context:

```bash
export AWS_PROFILE=poweruser
export AWS_REGION=us-west-2
aws sso login --profile "$AWS_PROFILE"
aws sts get-caller-identity
```

2. Confirm Terraform vars for role/region:

- `terraform/terraform.tfvars` should include:
  - `aws_region = "us-west-2"`
  - `lambda_architecture = "x86_64"`
  - `existing_lambda_role_arn = "arn:aws:iam::372765825616:role/lambda_role_multipart_upload"`

3. Create infrastructure and ECR repo:

```bash
cd terraform
terraform init
terraform apply -target=aws_ecr_repository.app
```

4. Build and push image to the exact ECR repo from Terraform state:

```bash
ECR_REPO_URL=$(terraform output -raw ecr_repository_url)
TAG=$(date +%Y%m%d%H%M%S)
IMAGE_URI="${ECR_REPO_URL}:${TAG}"
cd ..

aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin "$(echo "$ECR_REPO_URL" | cut -d/ -f1)"

docker buildx build --platform linux/amd64 --load -t $IMAGE_URI .
docker push $IMAGE_URI
```

5. Deploy Lambda + API Gateway using that image:

```bash
cd terraform
terraform apply -var="image_uri=$IMAGE_URI"
```

6. Get endpoints:

```bash
terraform output api_endpoint
terraform output mcp_endpoint
```

## Registering for GPT/MCP usage

Use Terraform output `mcp_endpoint` as your MCP server URL.

Manual MCP validation (stateless HTTP):

```bash
MCP_BASE="$(terraform output -raw api_endpoint)/mcp/"

curl -i "$MCP_BASE" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

curl -i "$MCP_BASE" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'

curl -i "$MCP_BASE" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"sample_opinions","arguments":{"subject":"RAG","limit":3}}}'
```

## Teardown and recreate demo

Destroy everything Terraform created:

```bash
cd terraform
terraform destroy
```

This configuration uses `force_delete = true` for the ECR repository, so `destroy` also removes pushed images in that repo.

Then follow the AWS deployment steps again from step 1.

## Notes

- This implementation is intentionally tool-first: the MCP tools handle cataloging, samples, stats, and concise summaries.
- Add authentication on API Gateway before exposing outside class/lab environments.
- Lambda runs a persistent ASGI server (`uvicorn`) with AWS Lambda Web Adapter.
- Use a unique image tag for each deploy (timestamp is fine). Terraform updates Lambda when `image_uri` changes.
