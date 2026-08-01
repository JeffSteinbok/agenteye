# AgentEye implementation instructions

- Follow `.github/copilot-instructions.md` and `DEVELOPMENT.md`; the approved issue and its acceptance criteria define the requested behavior.
- Reuse existing CLI, typed-model, API, frontend, and packaging patterns before introducing new abstractions.
- Keep platform-specific behavior behind explicit platform checks and preserve current behavior on other operating systems.
- Treat session databases, event logs, filesystem paths, process information, and configuration as sensitive local data. Do not add telemetry or transmit them externally.
- Add focused tests for new behavior and failure cases. For filesystem or platform integration, use temporary paths and mocks rather than changing the runner machine.
- Run the repository checks relevant to touched code. Python changes must satisfy Ruff, MyPy, and pytest; frontend changes must satisfy lint, typecheck, tests, and build.
- Update user-facing documentation for new commands, settings, installation behavior, limitations, or platform requirements.
- Do not merge, publish, release, or broaden the issue scope.