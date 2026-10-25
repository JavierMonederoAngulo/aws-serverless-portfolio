graph TD
    Client([🌐 Web Browser]) -->|HTTPS| CF[⚡ Amazon CloudFront]
    CF -->|Static Assets | S3[(🪣 Amazon S3 <br/> Origin Access Control)]
    CF -->|API Requests POST /chat| API[🚪 Amazon API Gateway]
    
    API -->|Throttled| Lambda[λ AWS Lambda <br/> Python Orchestrator]
    
    Lambda -->|Increment Counter| DB[(📊 Amazon DynamoDB)]
    Lambda -->|Invoke Model| Bedrock[🧠 Amazon Bedrock <br/> Claude Haiku EU]
    
    classDef aws fill:#FF9900,stroke:#232F3E,stroke-width:2px,color:black,font-weight:bold;
    classDef client fill:#4FB3FF,stroke:#232F3E,stroke-width:2px,color:black,font-weight:bold;
    
    class CF,S3,API,Lambda,DB,Bedrock aws;
    class Client client;