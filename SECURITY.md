# Security Policy

## Supported Versions

| Version | Security support |
| --- | --- |
| Latest stable release | Supported |
| Latest development build | Supported |
| Older releases and development builds | Not routinely supported |

Maintainers may backport fixes for critical issues to older releases at their discretion. To receive security fixes, update to the latest stable release or development build.

## Reporting a Vulnerability

Please do not report suspected vulnerabilities through public GitHub issues, discussions, or public Discord channels. Instead, submit a separate report for each distinct vulnerability using one of these reporting channels:

| Method | How-To |
| --- | --- |
| GitHub | Use the repository's [**Report a vulnerability**](https://github.com/Dispatcharr/Dispatcharr/security/advisories/new) button |
| Email | Send a report to [security@dispatcharr.tv](mailto:security@dispatcharr.tv) |

> [!WARNING]
> **Disclose AI assistance.** If you used AI assistance, check "I used AI assistance to find or write up this report" at the bottom of the GitHub report form, or disclose it in your email. Reports where there is reason to believe material AI assistance was not disclosed may be closed without further follow-up or attribution at the maintainers' discretion. Reporters are responsible for verifying their findings before submission.

Reports based solely on static code analysis, without a proof of concept, reproduction steps, or another concrete demonstration of security impact, may be closed without further follow-up or attribution. A suspected issue in source code is not sufficient on its own.

At the maintainers' discretion, reporters may be asked to submit low-impact issues assessed as medium severity or lower as regular bug reports instead of security advisories.

Deliberately misrepresenting an issue or repeatedly inflating severity to bypass this policy may result in reports being closed or the reporter being blocked, at the maintainers' discretion.

Only test instances you own or have permission to test.

### Include in Your Report

Include as much of the following as possible:

- The affected Dispatcharr version or development build.
- Deployment details and relevant configuration.
- Steps to reproduce, a proof of concept, or another concrete demonstration of security impact.
- The potential impact and affected components or endpoints.
- Relevant logs, request and response details, or screenshots. Do not include passwords, API keys, tokens, stream URLs, or other secrets.

### Coordinated Disclosure

Maintainers will review reports as resources permit, assess their impact, and may contact you for additional information or to validate a fix.

Disclosure is determined case by case, taking into account the issue's severity, impact, and the project's current release stage. Maintainers may coordinate disclosure with the reporter, publish a security advisory, or credit the reporter in a security entry in the [changelog](CHANGELOG.md), as appropriate.

__Public disclosure is your choice.__ We ask that you give maintainers a reasonable opportunity to investigate and address the issue before sharing details publicly.
