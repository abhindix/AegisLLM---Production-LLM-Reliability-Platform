# AegisLLM Financial Team Demo Summary

## Purpose
This demo shows a production-style credit decision workflow powered by a FastAPI gateway, Postgres-backed records, Redis caching, Kafka eventing, and an LM Studio-connected LLM path. It is designed for financial teams evaluating explainable, operationally safe AI for underwriting and risk workflows.

## Live application status
- App URL: http://localhost:18080/investor
- Health endpoint: http://localhost:18080/health/ready
- Credit workflow endpoint: POST /credit/applications
- Credit scoring endpoint: POST /credit/applications/{application_id}/score
- Fraud check endpoint: POST /credit/applications/{application_id}/fraud-check
- Decision endpoint: POST /credit/applications/{application_id}/decision
- LM Studio chat endpoint: POST /v1/chat/completions

## What the demo proves
- A credit application can be created and stored.
- A scoring function evaluates affordability and risk based on a deterministic pricing model.
- A fraud check can assess duplicate/sanctions/risk signals.
- A final decision is produced and logged.
- The UI supports live interaction from the browser.
- The app can call an LM Studio / OpenAI-compatible model for chat-based reasoning.

## Working live examples

### 1) Good credit example
Prompt:

```text
Assess the credit risk for this applicant and provide a short decision summary.

Applicant profile:
- Credit history: 2 prior auto loans, one paid on time, one late by 18 days 2 years ago, no defaults
- Income: $96,000 annual salary from full-time employment
- Debt-to-income ratio: 28%
- Employment status: Salaried, employed for 6 years
- Recent financial changes: No recent job loss; added a small personal loan 4 months ago
- Requested loan: $25,000 personal loan, 36-month term
- Credit score: 720

Return:
1. Risk level: low / medium / high
2. One-sentence recommendation
3. Key factors that support the decision
```

Expected result: low risk, likely approve with standard terms.

### 2) Bad credit example
Prompt:

```text
Assess the credit risk for this applicant and provide a short decision summary.

Applicant profile:
- Credit history: Multiple missed payments, one charge-off 3 years ago, recent collections activity
- Income: $42,000 annual income from part-time work
- Debt-to-income ratio: 58%
- Employment status: Self-employed with inconsistent monthly earnings
- Recent financial changes: Recent job change, new credit card debt, increased monthly obligations
- Requested loan: $18,000 personal loan, 24-month term
- Credit score: 540

Return:
1. Risk level: low / medium / high
2. One-sentence recommendation
3. Key factors that support the decision
```

Expected result: high risk, likely decline or manual review.

### 3) Manual review example
Prompt:

```text
You are a credit-risk analyst. Evaluate the applicant below using only the information provided.

- Credit history: Clean record except one late payment 2 years ago
- Income: $110,000 per year
- Debt-to-income ratio: 31%
- Employment status: Full-time salaried employee
- Recent financial changes: None
- Credit score: 740
- Requested loan amount: $30,000
- Loan term: 48 months

Provide:
- risk assessment
- approval recommendation
- rationale in 3 bullet points
```

Expected result: moderate risk, likely manual review or approval with caution depending on policy.

## API example

```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [
    {
      "role": "user",
      "content": "Assess the credit risk for this applicant and provide a short decision summary.\n\nApplicant profile:\n- Credit history: 2 prior auto loans, one paid on time, one late by 18 days 2 years ago, no defaults\n- Income: $96,000 annual salary from full-time employment\n- Debt-to-income ratio: 28%\n- Employment status: Salaried, employed for 6 years\n- Recent financial changes: No recent job loss; added a small personal loan 4 months ago\n- Requested loan: $25,000 personal loan, 36-month term\n- Credit score: 720\n\nReturn:\n1. Risk level: low / medium / high\n2. One-sentence recommendation\n3. Key factors that support the decision"
    }
  ],
  "max_tokens": 220,
  "temperature": 0.2
}
```

## Demo flow for financial teams
1. Open the investor page at http://localhost:18080/investor.
2. Fill in the credit application form.
3. Click Run credit workflow.
4. Confirm the response shows application creation, risk score, fraud result, and decision.
5. Use the LM Studio prompt section to test the model with structured applicant data.
6. Explain that the backend keeps a deterministic risk pipeline while the LLM supports assistant-style summarization and rationale.

## Key takeaway
This is a production-style demo for regulated AI in credit workflows: explainable structured scoring, operational controls, auditability, and optional LLM-based reasoning. It is suitable for showing how AegisLLM can support underwriting workflows without losing control over model outputs or governance.

## Verification summary
- Browser flow validated: credit workflow executed successfully and produced a result payload.
- App health was validated through the live service endpoints.
- LM Studio path is configured for the model openai/gpt-oss-20b and is ready for live demonstration when the model service is reachable.

## Recommended live narrative for the meeting
“Here is a regulated credit workflow demo in which we ingest applicant data, score the application, run fraud checks, generate a final decision, and optionally ask a language model to explain the rationale. This demonstrates a governance-friendly AI workflow with deterministic decisioning and operational observability.”
