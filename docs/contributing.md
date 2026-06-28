---
title: Contributing
layout: default
nav_order: 8
---

# Contributing
{: .no_toc }

Thank you for your interest in contributing! Here's how to get involved.
{: .fs-6 .fw-300 }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Code of Conduct

Be respectful and constructive. We're all here to build something useful.

## Reporting Bugs

Open an [issue](https://github.com/JeffSteinbok/agenteye/issues) with:

- A clear description of the problem
- Steps to reproduce
- Expected vs. actual behavior
- Your OS, Python version, and package version

## Suggesting Features

Open an [issue](https://github.com/JeffSteinbok/agenteye/issues) with the `enhancement` label and describe what you'd like and why.

## Submitting Code

1. **Fork** the repository and create your branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. Make your changes following the [Development Guide]({{ site.baseurl }}/development).
3. Ensure all CI checks pass (lint, type check, tests):
   ```bash
   ruff check src/
   ruff format src/
   mypy src/
   python -m pytest tests/ -v --tb=short
   ```
4. **Open a Pull Request** against `main` — direct pushes to `main` are not allowed.
5. A maintainer will review your PR. Please be patient and responsive to feedback.

## Branch Naming

| Prefix | Use for |
|:-------|:--------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `chore/` | Maintenance, dependencies, CI |
| `docs/` | Documentation changes |

Keep PRs focused — one feature or fix per PR.

## Development Setup

See the [Development Guide]({{ site.baseurl }}/development) for full instructions on setting up a local dev environment, running tests, and linting.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](https://github.com/JeffSteinbok/agenteye/blob/main/LICENSE).
