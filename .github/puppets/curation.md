# AgentEye curation instructions

- Check for duplicates and overlap with existing issues and pull requests before proposing implementation.
- Keep each implementation scoped to one independently testable change. Split broad work into linked child issues.
- Prefer existing modules and typed models described in `DEVELOPMENT.md`; avoid parallel abstractions.
- Flag changes that expose local session data, weaken process-safety checks, alter destructive defaults, or require credentials as `needs-human`.
- Preserve cross-platform behavior unless the approved issue explicitly scopes the change to one operating system.