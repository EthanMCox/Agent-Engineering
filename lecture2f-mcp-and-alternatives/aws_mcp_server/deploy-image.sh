#!/bin/bash

#Run this script from the terraform directory (e.g., ../deploy-image.sh)

ECR_REPO_URL=$(terraform output -raw ecr_repository_url)
cd ..
echo "ECR_REPO_URL => [${ECR_REPO_URL}]"
TAG=$(date +%Y%m%d%H%M%S)
export IMAGE_URI="${ECR_REPO_URL}:${TAG}"
echo "IMAGE_URI => ${IMAGE_URI}"

aws ecr get-login-password --region $AWS_REGION | \
  docker login --username AWS --password-stdin "$(echo "$ECR_REPO_URL" | cut -d/ -f1)"

docker buildx build --platform linux/amd64 --load -t $IMAGE_URI .
docker push $IMAGE_URI

cd terraform
terraform apply -var="image_uri=$IMAGE_URI"
