import * as assert from 'assert';
import { getWebviewContent } from '../webview';
import type { BackendState } from '../backend';

// Minimal vscode stub for non-API tests
const mockVscode = {
  Uri: { file: (p: string) => ({ fsPath: p }) },
  ViewColumn: { One: 1 },
};

suite('Webview Content', () => {
  test('connected state renders iframe pointing to localhost', () => {
    const state: BackendState = { kind: 'connected', version: '1.0.0', sessionCount: 3 };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('iframe'));
    assert.ok(html.includes('http://localhost:5111'));
    assert.ok(html.includes('Content-Security-Policy'));
  });

  test('checking state renders spinner', () => {
    const state: BackendState = { kind: 'checking' };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('Checking'));
    assert.ok(html.includes('spinner'));
  });

  test('starting state shows elapsed time', () => {
    const state: BackendState = { kind: 'starting', elapsed: 5 };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('5s'));
    assert.ok(html.includes('Starting'));
  });

  test('disconnected state shows retry button', () => {
    const state: BackendState = { kind: 'disconnected' };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('retry'));
    assert.ok(html.includes('unreachable'));
  });

  test('error setup-required shows install button', () => {
    const state: BackendState = {
      kind: 'error',
      subtype: 'setup-required',
      message: 'Backend needs install',
    };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('install'));
    assert.ok(html.includes('Welcome'));
  });

  test('error port-conflict shows message', () => {
    const state: BackendState = {
      kind: 'error',
      subtype: 'port-conflict',
      message: 'Port 5111 is in use',
    };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes('Port 5111'));
    assert.ok(html.includes('retry'));
  });

  test('connected state uses custom port', () => {
    const state: BackendState = { kind: 'connected', version: '2.0.0', sessionCount: 0 };
    const html = getWebviewContent(state, 9999);
    assert.ok(html.includes('http://localhost:9999'));
  });

  test('CSP restricts frame-src to port', () => {
    const state: BackendState = { kind: 'connected', version: '1.0.0', sessionCount: 1 };
    const html = getWebviewContent(state, 5111);
    assert.ok(html.includes("frame-src http://localhost:5111"));
  });
});
