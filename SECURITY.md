# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.0.x   | ✅ Yes    |
| 1.0.x   | ❌ No     |

## Security Design

VaidyaBridge is designed with the following security principles:

- **No data persistence**: All patient data is processed in-memory and never stored
- **DPDP Act compliance**: Zero PII retention per India's Digital Personal Data Protection Act 2023
- **Non-root container**: Docker container runs as UID 1001 (non-root)
- **Input sanitisation**: All inputs validated and stripped of control characters
- **Rate limiting**: 10 requests/minute per IP (sliding window)
- **Request size limits**: Maximum 5 MB per request
- **Security headers**: X-Content-Type-Options, X-Frame-Options, CSP on all responses
- **XSS prevention**: All user-facing output HTML-escaped in frontend JS
- **No API key logging**: Keys never written to logs or error responses
- **Stateless processing**: No session state, no database, no file writes

## Reporting a Vulnerability

To report a security vulnerability, please open a GitHub Issue marked `[SECURITY]`.

Do **not** include sensitive information in public issues.
