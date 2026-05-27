# Security Policy

## Supported Versions

`ghcp-cli-dashboard` follows a rolling-release model. Only the latest
published version on PyPI receives security fixes.

| Version | Supported          |
| ------- | ------------------ |
| latest  | :white_check_mark: |
| older   | :x:                |

Always upgrade to the latest version (`pip install -U ghcp-cli-dashboard`)
before reporting a vulnerability.

## Reporting a Vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via GitHub Security Advisories:

1. Go to <https://github.com/JeffSteinbok/ghcpCliDashboard/security/advisories/new>
2. Provide:
   - A clear description of the vulnerability and the affected
     component (CLI command, API endpoint, frontend route, etc.)
   - Steps to reproduce, including version numbers and OS
   - The impact you've assessed (e.g. local-network exposure, RCE,
     data exposure)
   - Any suggested mitigation, if known

You should receive an acknowledgement within **5 business days**. We aim to
provide a fix or detailed mitigation plan within **30 days** for confirmed
vulnerabilities, prioritized by severity.

## Scope

`ghcp-cli-dashboard` is a **local-first** tool. The default deployment
binds to `127.0.0.1` only and requires a per-instance random API token
for every `/api/*` request. Findings particularly in scope include:

- Authentication / authorization bypass on `/api/*` endpoints
- Code injection (RCE) via session data, sync folder, or update flow
- Path traversal or unauthorized filesystem access
- Cross-site scripting (XSS) in any rendered HTML or JSON
- DNS-rebinding or `Host`-header attacks against the local server
- Supply-chain weaknesses in build, release, or distribution

Findings explicitly **out of scope**:

- Issues that require an attacker to already have local code execution
  on the same machine as the user
- Denial-of-service via resource exhaustion (the dashboard is a local
  tool with no SLA)
- Theoretical attacks against third-party dependencies without a
  demonstrated exploit path through this codebase

## Responsible Disclosure

We follow coordinated disclosure. Please give us a reasonable window
(typically 90 days) to ship a fix before publishing details. We will
credit reporters in release notes unless anonymity is requested.
