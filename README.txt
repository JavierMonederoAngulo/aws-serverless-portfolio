```mermaid
graph TD
    Client([🌐 Web Browser]) -->|HTTPS| CF[⚡ Amazon CloudFront]
    CF -->|Static Assets| S3[(🪣 Amazon S3 - OAC)]
    CF -->|POST /chat & /visit| API[🚪 Amazon API Gateway]
    API -->|Throttled| Lambda[λ AWS Lambda - Python]
    Lambda -->|Atomic Counter| DB[(📊 Amazon DynamoDB)]
    Lambda -->|Invoke Model| Bedrock[🧠 Amazon Bedrock - Claude Haiku EU]
```