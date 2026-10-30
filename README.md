# ☁️ Serverless Cloud Portfolio & GenAI CV Assistant on AWS

🌐 **Live Demo:** [https://d3vjauql06bl7n.cloudfront.net](https://d3vjauql06bl7n.cloudfront.net)

A 100% serverless personal portfolio and interactive AI assistant built on **AWS (`eu-west-1`)** using Infrastructure as Code (**AWS SAM**). Designed to demonstrate cloud architecture patterns, security best practices, and practical Generative AI integration.

---

## 🏗️ Architecture

![AWS Architecture Diagram](arquitectura.png)

### Request Flow
1. **Static Edge Delivery:** Users access the frontend over HTTPS via **Amazon CloudFront**. Static assets (`index.html`) are stored in a private **Amazon S3** bucket with all public access blocked, accessible strictly through CloudFront **Origin Access Control (OAC)**.
2. **Serverless API Layer:** Asynchronous `POST /visit` and `POST /chat` requests are routed through **Amazon API Gateway** (HTTP API) with CORS and rate-limiting enabled.
3. **Compute & Orchestration:** **AWS Lambda** (Python 3.12, `arm64`, `boto3`) processes incoming requests under strict least-privilege IAM roles:
   - `/visit`: Performs atomic counter updates in **Amazon DynamoDB**.
   - `/chat`: Validates input & conversation bounds, injects CV context from RAM (loaded once during Lambda Cold Start) alongside stateless multi-turn history (up to 3 prior turns / 6 messages), invokes **Amazon Bedrock** (`eu.anthropic.claude-haiku-4-5`) via an EU Cross-Region Inference profile, and returns live execution & FinOps telemetry (`cold_start`, `latency_ms`, `input_tokens`, `output_tokens`, `estimated_cost_usd`).

---

## 🛡️ AWS Well-Architected Highlights

* **Security:**
  * **Zero-Secret CI/CD:** Automated deployments via **GitHub Actions** using **AWS IAM OpenID Connect (OIDC)** federation—no static long-lived AWS credentials stored in GitHub.
  * **Private Storage:** S3 bucket secured with Origin Access Control (OAC).
  * **API & Payload Protection:** API Gateway configured with throttling (`RateLimit: 5 req/s`, `BurstLimit: 10`) combined with strict pre-inference Lambda input guards (question `<= 500` chars, history `<= 6` alternating `user`/`assistant` messages of `<= 1,000` chars each) that reject malformed payloads with `HTTP 400` before invoking Bedrock.
  * **GDPR Data Residency:** Bedrock calls use the `eu.` inference profile, ensuring prompts and completions remain strictly within European Union AWS regions.
* **Operational Excellence & Performance Efficiency:**
  * **Infrastructure as Code (IaC):** Entire stack declaratively defined in `template.yaml` using **AWS SAM** and validated with automated unit tests (`unittest`/`pytest`).
  * **Distributed Tracing & Live Telemetry:** **AWS X-Ray** (`Tracing: Active`) enabled across API Gateway and Lambda, complemented by a real-time terminal telemetry bar in the chat UI displaying **Cold vs. Warm Start** state, inference latency (`ms`), token usage (`in`/`out`), and estimated cost per query.
  * **Stateless Multi-Turn Memory:** The browser maintains a sliding window of up to 6 messages (3 turns) in session memory with a one-click `Clear` reset, enabling natural follow-up questions with zero server-side state or database overhead.
* **Cost Optimization (FinOps):**
  * **Serverless Pay-Per-Use:** Zero idle compute costs; leverages AWS *Always Free* tier allowances for CloudFront, Lambda (`arm64`), DynamoDB, and X-Ray.
  * **In-Memory Context Injection (No RAG / No Prompt Caching):** CV context (`cv.txt`, ~1,000 tokens) is packaged directly within the Lambda artifact and loaded into RAM once during Cold Start—eliminating S3 `GetObject` calls on every request. Both RAG/vector indexes and Bedrock Prompt Caching are intentionally omitted because the full corpus fits comfortably in the context window and sits below Claude Haiku 4.5's 2,048-token minimum caching threshold.
  * **Cost Guardrails:** Output capped at `max_tokens: 300`, sliding history window capped at 6 messages, and monitored via **AWS Budgets** with automated billing alerts at **$1.00 USD**.

---

## 🛠️ Tech Stack

* **Cloud & IaC:** AWS (S3, CloudFront, API Gateway, Lambda, DynamoDB, Bedrock, IAM OIDC, X-Ray, Budgets), AWS SAM
* **Backend:** Python 3.12 (`boto3`)
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (zero framework overhead)
* **CI/CD:** GitHub Actions

---

## 📬 Contact

* **Author:** Javier Monedero Angulo — BSc Information Systems Engineering Student at UPM (Madrid)
* **LinkedIn:** [linkedin.com/in/javier-monedero-angulo-798248445](https://www.linkedin.com/in/javier-monedero-angulo-798248445)
* **Email:** [javier.monedero@outlook.com](mailto:javier.monedero@outlook.com)