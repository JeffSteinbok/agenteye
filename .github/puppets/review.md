# AgentEye review instructions

- Review against every acceptance criterion in the approved issue and identify any criterion without implementation or test evidence.
- Require focused regression tests, clear errors, idempotency where promised, and safe handling of user files and processes.
- Check that platform-specific changes preserve behavior on unsupported or unaffected operating systems.
- Reject new transmission of session data, local paths, process details, or configuration unless explicitly approved.
- Confirm Python and frontend checks appropriate to the diff are represented in CI.
- Treat release, publishing, auto-merge, and unrelated refactors as out of scope.