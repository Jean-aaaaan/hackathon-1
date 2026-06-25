# Vantage — Threat Model & Compliance Matrix
**Version:** 1.0  
**Date:** 2026-05-26  
**Author:** Carol (Security Architect)  
**Mode:** ENTERPRISE — SOC2 Type II + ISO27001 from Sprint 1

---

## 1. Threat Model (STRIDE)

### Asset Inventory
| Asset | Classification | Owner | Risk Level |
|-------|---------------|-------|-----------|
| Account State Object (ASO) | Confidential | Workspace admin | CRITICAL |
| HubSpot OAuth tokens | Highly Confidential | System | CRITICAL |
| Gong API keys | Highly Confidential | System | CRITICAL |
| Draft email content | Confidential | Rep | HIGH |
| Workspace user PII | Confidential | Workspace admin | HIGH |
| Audit logs | Restricted | Compliance | HIGH |
| API keys (Vantage-issued) | Highly Confidential | Workspace admin | HIGH |
| LLM prompt content (account data) | Confidential | System | MEDIUM |

### STRIDE Analysis

| Threat | Vector | Mitigation | Status |
|--------|--------|-----------|--------|
| **Spoofing** | Forged WorkOS JWT | Server-side JWT validation on every request (WorkOS SDK, not manual) | ✅ Mitigated |
| **Spoofing** | Stolen API key | Keys stored as bcrypt hashes; prefix-only shown after creation; short expiry option | ✅ Mitigated |
| **Spoofing** | HubSpot webhook replay | HMAC-SHA256 signature validation + timestamp check (< 5 min window) | ✅ Mitigated |
| **Tampering** | Cross-workspace account access | workspace_id filter on every query + PostgreSQL RLS as defense-in-depth | ✅ Mitigated |
| **Tampering** | SQL injection via account search | Parameterised queries everywhere (SQLAlchemy ORM) + pgvector semantic search | ✅ Mitigated |
| **Tampering** | Audit log manipulation | Append-only audit_log table (no DELETE permission granted to app role) | ✅ Mitigated |
| **Repudiation** | Rep denies approving draft | audit_log entry per approval; user_id, timestamp, final_content, IP logged | ✅ Mitigated |
| **Info Disclosure** | LLM prompt injection in chat | System prompt hardened; account_id binding enforced; no cross-account data in context | ✅ Mitigated |
| **Info Disclosure** | API key exposure in logs | Keys never logged; prefix-only in error messages | ✅ Mitigated |
| **Info Disclosure** | ASO data in Next.js RSC leak | API responses server-to-server only; no raw ASO in client bundle | ✅ Mitigated |
| **DoS** | Nightly pipeline overwhelm | Azure Service Bus rate limiting; per-workspace processing locks (Redis NX) | ✅ Mitigated |
| **DoS** | API rate abuse | Per-API-key rate limits (Redis token bucket); 429 with Retry-After | ✅ Mitigated |
| **Elevation of Privilege** | Rep accessing another user's accounts | workspace_id + owner_user_id scoping; manager role required for cross-rep view | ✅ Mitigated |
| **Elevation of Privilege** | API key scope escalation | Scopes enforced at middleware; read-only keys cannot POST | ✅ Mitigated |

### Residual Risks
| Risk | Severity | Owner | Mitigation Plan |
|------|---------|-------|----------------|
| LLM hallucination in drafts | MEDIUM | Nova + Grounding Agent | GroundingAgent verifies every fact before surfacing; confidence scores shown |
| Third-party AI data retention (Anthropic, Perplexity) | MEDIUM | Carol | Data processing agreements with both vendors; no PII in prompts (account name only) |
| HubSpot OAuth token theft via SSRF | LOW | Kai + Carol | No user-supplied URLs processed; SSRF protection in Container App network rules |
| Insider threat (Vantage team access) | LOW | Carol | Key Vault access logs; least-privilege Azure RBAC; Vantage staff cannot access customer data in prod |

---

## 2. SOC2 Type II Control Matrix

### CC6: Logical Access Controls

| Control | Requirement | Implementation | Evidence |
|---------|------------|---------------|---------|
| CC6.1 | Access restricted by role | WorkOS roles (rep/manager/admin/owner) + API scope enforcement | WorkOS logs + unit tests |
| CC6.2 | Authentication required | WorkOS JWT on all app routes; API key on all API routes | E2E tests pass gate |
| CC6.3 | MFA available | WorkOS TOTP + passkeys enabled | WorkOS dashboard config |
| CC6.7 | Access revoked on termination | WorkOS user deactivation + API key revocation flow | Workspace admin UI |
| CC6.8 | Audit trail of access | audit_log table: every auth event, every data access | audit_log entries |

### CC7: System Operations

| Control | Requirement | Implementation | Evidence |
|---------|------------|---------------|---------|
| CC7.1 | Change management | GitHub PR reviews (min 1 approval) + CI gates | GitHub PR history |
| CC7.2 | Monitoring and alerting | Azure Monitor + PostHog + Sentry | Alert configs in IaC |
| CC7.3 | Incident response | Runbook in docs/runbooks/ | Runbook doc |
| CC7.5 | Vulnerability management | Dependabot + Snyk in CI; critical CVEs blocked | CI pipeline config |

### CC8: Change Management

| Control | Requirement | Implementation | Evidence |
|---------|------------|---------------|---------|
| CC8.1 | Authorised changes only | Branch protection; no direct pushes to main | GitHub repo settings |
| CC8.1 | Testing before deployment | CI pipeline: lint → test → build → security scan | GitHub Actions logs |

### CC9: Risk Mitigation

| Control | Requirement | Implementation | Evidence |
|---------|------------|---------------|---------|
| CC9.2 | Third-party risk | DPAs with Anthropic, Perplexity, WorkOS, HubSpot, Gong | Vendor DPA files |

---

## 3. Security Requirements for Every Story

Every story touching auth, data access, or external integrations MUST include:

### Mandatory Security Checklist (Carol reviews at Gate 5)

```
Auth & Access:
□ WorkOS JWT validated server-side (not client-side)
□ workspace_id included in all DB queries
□ Role requirement documented and enforced
□ API key scope validation for API-exposed endpoints

Data:
□ No PII in LLM prompts (use account_id, not email addresses)
□ No secrets in logs, errors, or API responses
□ Parameterised queries (no string concatenation in SQL)
□ Sensitive fields excluded from general list responses

Audit:
□ State-changing operations logged to audit_log
□ Before/after diff included for account state changes
□ User ID and timestamp in every audit entry

Webhooks:
□ HMAC signature validated before processing
□ Idempotency key checked (prevent replay)
□ Timestamp validation (< 5 min window)

External API calls:
□ Timeout set (max 30s)
□ Error caught and handled gracefully
□ No customer data in error messages returned to client
```

---

## 4. Data Privacy (GDPR/PDPA/CCPA)

| Requirement | Implementation |
|------------|---------------|
| Data minimisation | ASO contains only sales-relevant data; no health/financial/government ID |
| Right to access | Workspace admin can export full ASO per account via API |
| Right to deletion | Soft delete + 30-day hard delete job; webhooks stop on disconnect |
| Data residency | Azure regions: Southeast Asia (APAC), UAE North (MENA), West Europe (EU), East US (US) |
| Data retention | ASO: retained while workspace active; interactions: 3 years; audit_log: 7 years |
| Processor agreements | DPAs with all sub-processors (Anthropic, Perplexity, WorkOS, Azure) |

---

## 5. Penetration Testing Schedule (Ethan)

- Sprint 1-2: Auth flows + API authentication
- Sprint 3-4: Agent Inbox + draft approval flows
- Sprint 5-6: Watchtower + cross-tenant access attempts
- Sprint 7-8: API platform + rate limiting bypass attempts
- Sprint 9-10: Full application pentest before v1.0 release
- Post-launch: Quarterly automated scans + annual manual pentest

*Carol sign-off required on every release. No exceptions.*
