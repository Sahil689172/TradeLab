@echo off
REM TradeLab AWS deployment helper — Windows CMD
REM Run these commands manually one at a time. Read each section comment first.
REM
REM Prerequisites: AWS CLI v2 installed, configured with your IAM credentials.
REM   aws configure   (set region to ap-south-1 or your preferred region)

SET REGION=ap-south-1
SET APP=tradelab
SET ACCOUNT_ID=
REM ^^^ Set ACCOUNT_ID to your 12-digit AWS account number before running.

REM ── 1. Create ECR repository ──────────────────────────────────────────────
aws ecr create-repository --repository-name %APP% --region %REGION%

REM ── 2. Authenticate Docker to ECR ─────────────────────────────────────────
aws ecr get-login-password --region %REGION% | docker login --username AWS --password-stdin %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com

REM ── 3. Build and push the Docker image ────────────────────────────────────
REM Run from the project root (where Dockerfile lives).
docker build -t %APP%:latest .
docker tag %APP%:latest %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/%APP%:latest
docker push %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/%APP%:latest

REM ── 4. Store secrets in AWS Secrets Manager ───────────────────────────────
REM Replace YOUR_KEY_HERE with actual key values.
aws secretsmanager create-secret --name tradelab/gemini-api-key --secret-string "YOUR_GEMINI_KEY_HERE" --region %REGION%
aws secretsmanager create-secret --name tradelab/groq-api-key --secret-string "YOUR_GROQ_KEY_HERE" --region %REGION%

REM ── 5. Apply Terraform (creates App Runner + S3 + CloudFront) ─────────────
REM Requires Terraform >= 1.5 installed.
cd aws
terraform init
terraform plan -var="ecr_image_uri=%ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/%APP%:latest" -var="gemini_api_key_arn=ARN_FROM_STEP_4" -var="groq_api_key_arn=ARN_FROM_STEP_4"
REM Review the plan, then apply:
terraform apply -var="ecr_image_uri=%ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/%APP%:latest" -var="gemini_api_key_arn=ARN_FROM_STEP_4" -var="groq_api_key_arn=ARN_FROM_STEP_4"

REM ── 6. Build and deploy the frontend ──────────────────────────────────────
cd ..\frontend
REM Set VITE_API_BASE to the CloudFront URL from terraform output
set VITE_API_BASE=https://YOUR_CLOUDFRONT_DOMAIN
npm run build
aws s3 sync dist/ s3://tradelab-frontend-%ACCOUNT_ID%/ --delete
aws cloudfront create-invalidation --distribution-id YOUR_CF_DIST_ID --paths "/*"

REM ── 7. Verify health ──────────────────────────────────────────────────────
REM Replace URL with your App Runner service URL from terraform output.
curl https://YOUR_APPRUNNER_URL/health
