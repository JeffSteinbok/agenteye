import * as assert from 'assert';

// Test the token extraction regex in isolation
suite('Token Extraction', () => {
  const TOKEN_REGEX = /window\.__DASHBOARD_TOKEN__\s*=\s*"([^"]+)"/;

  test('extracts token from injected script', () => {
    const html = `<html><head><script>window.__DASHBOARD_TOKEN__="abc123xyz";</script></head></html>`;
    const match = html.match(TOKEN_REGEX);
    assert.ok(match);
    assert.strictEqual(match![1], 'abc123xyz');
  });

  test('extracts token with spaces around equals', () => {
    const html = `<script>window.__DASHBOARD_TOKEN__ = "token-with-dashes_and_stuff";</script>`;
    const match = html.match(TOKEN_REGEX);
    assert.ok(match);
    assert.strictEqual(match![1], 'token-with-dashes_and_stuff');
  });

  test('returns null when no token in HTML', () => {
    const html = `<html><head></head><body><h1>Hello</h1></body></html>`;
    const match = html.match(TOKEN_REGEX);
    assert.strictEqual(match, null);
  });

  test('handles urlsafe base64 tokens', () => {
    const token = 'aB3-xY7_Zq2Wk9mN5pR1sT4uV6wX8yZ0bC2dE4fG6hJ';
    const html = `<script>window.__DASHBOARD_TOKEN__="${token}";</script>`;
    const match = html.match(TOKEN_REGEX);
    assert.ok(match);
    assert.strictEqual(match![1], token);
  });
});
