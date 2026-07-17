# Testing Conventions

## Structure

```
src/test/
├── token.test.ts          Pure logic tests (run with mocha)
├── webview.test.ts        Webview content tests (requires VS Code test runner)
└── testing-conventions.md This file
```

## Two test tiers

### 1. Unit tests (mocha, `npm test`)

Pure functions that don't need the VS Code API:
- Token extraction regex
- URL construction
- State machine transitions (when extracted to pure functions)

Run with: `npm test` (mocha + ts-node, TDD UI)

### 2. Integration tests (VS Code test runner)

Anything importing `vscode` — webview rendering, command registration, state transitions through the real extension host.

Run with: F5 → Extension Tests launch config (TODO: set up `@vscode/test-electron`)

## Naming

```typescript
test('describes what it verifies', () => { ... });
```

Use plain English descriptions. No `MethodName_Scenario_Expected` — tests are short enough to be self-documenting.

## Assertions

- Use `assert.ok()` for truthy checks
- Use `assert.strictEqual()` for value equality
- Use `assert.match()` for regex matching on strings

## What to test

- **Do test**: pure logic, regex patterns, URL construction, state transitions
- **Don't test**: VS Code API wrappers, trivial getters, webview HTML structure details (fragile)
- **Integration**: full activation → connected flow (requires VS Code test runner)

## Adding tests

1. Pure logic → `src/test/{module}.test.ts`, add to `npm test` glob if needed
2. VS Code-dependent → `src/test/{module}.test.ts`, use `suite`/`test` with `@vscode/test-electron`
