/**
 * Minimal vscode module mock for running unit tests outside the Extension Host.
 * Register this via --require before importing any source that uses 'vscode'.
 *
 * Strategy: Inject a synthetic cache entry keyed by the resolved path that
 * @types/vscode would point to. Since `vscode` is listed in externals and
 * has @types/vscode installed, Node resolves it to the @types stub's directory.
 * We preload the cache so require('vscode') returns our mock before it tries
 * to actually find a real module.
 */

const noop = (): any => {};

const vscodeMock = {
  Uri: {
    file: (p: string) => ({ fsPath: p }),
    parse: (u: string) => ({ toString: () => u }),
  },
  ViewColumn: { One: 1, Two: 2 },
  window: {
    createStatusBarItem: () => ({ show: noop, hide: noop, dispose: noop, text: '', tooltip: '', command: '' }),
    createOutputChannel: () => ({ appendLine: noop, dispose: noop }),
    createWebviewPanel: () => ({
      webview: { html: '', onDidReceiveMessage: noop },
      reveal: noop,
      onDidDispose: noop,
      dispose: noop,
    }),
    showInformationMessage: noop,
    showWarningMessage: noop,
    showErrorMessage: noop,
  },
  workspace: {
    getConfiguration: () => ({ get: (_key: string, defaultVal?: unknown) => defaultVal }),
    onDidChangeConfiguration: noop,
    workspaceFolders: undefined,
    openTextDocument: () => Promise.resolve({}),
  },
  commands: { executeCommand: noop, registerCommand: () => ({ dispose: noop }) },
  env: { openExternal: noop },
  EventEmitter: class {
    event = noop;
    fire = noop;
    dispose = noop;
  },
  StatusBarAlignment: { Left: 1, Right: 2 },
};

// Use Node's Module._cache to intercept require('vscode').
// We find the path that require.resolve would use and preload our mock.
const path = require('path');
const Module = require('module');

// Create a fake module entry
const fakeModulePath = path.join(__dirname, '..', '..', 'node_modules', 'vscode', 'index.js');
const fakeModule = new Module(fakeModulePath);
fakeModule.filename = fakeModulePath;
fakeModule.loaded = true;
fakeModule.exports = vscodeMock;

// Inject into the cache. require('vscode') resolves via node_modules lookup,
// but since there's no real vscode package, we need to intercept at the resolver level.
// The simplest way: override require itself on the Module prototype.
const originalRequire = Module.prototype.require;
Module.prototype.require = function (id: string) {
  if (id === 'vscode') {
    return vscodeMock;
  }
  return originalRequire.apply(this, arguments);
};

