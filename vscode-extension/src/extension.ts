import * as vscode from 'vscode';
import { BackendManager } from './backend';
import { openEditorPanel } from './webview';
import { StatusBarManager } from './statusBar';

let editorPanel: vscode.WebviewPanel | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const backend = new BackendManager();
  const statusBar = new StatusBarManager(context, backend);

  // Track connected state for welcome view
  backend.onStateChange(state => {
    vscode.commands.executeCommand('setContext', 'agenteye.connected', state.kind === 'connected');

    // Auto-open editor tab on first connect
    if (state.kind === 'connected' && !editorPanel) {
      vscode.commands.executeCommand('agenteye.openDashboard');
    }
  });

  // Register "Open Dashboard" command — opens editor tab
  context.subscriptions.push(
    vscode.commands.registerCommand('agenteye.openDashboard', () => {
      if (editorPanel) {
        editorPanel.reveal();
        return;
      }
      editorPanel = openEditorPanel(backend, context.extensionUri);
      vscode.commands.executeCommand('setContext', 'agenteye.dashboardOpen', true);
      editorPanel.onDidDispose(() => {
        editorPanel = undefined;
        vscode.commands.executeCommand('setContext', 'agenteye.dashboardOpen', false);
      });

      // Trigger activation if not yet activated
      if (backend.state.kind === 'checking') {
        backend.activate();
      }
    }),
  );

  // Register "Stop Backend" command
  context.subscriptions.push(
    vscode.commands.registerCommand('agenteye.stopBackend', () => {
      backend.stopBackend();
    }),
  );

  // Listen for settings changes
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration('agenteye.port')) {
        backend.onPortChanged();
      }
    }),
  );

  // Start backend detection immediately
  backend.activate();

  // Cleanup
  context.subscriptions.push(backend);
  context.subscriptions.push(statusBar);
}

export function deactivate(): void {
  // Extension does NOT stop the server (no-ownership model)
}
