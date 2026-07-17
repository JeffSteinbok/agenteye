import * as vscode from 'vscode';
import { BackendManager, BackendState } from './backend';

/**
 * Renders the webview HTML for all backend states.
 * Used by both the sidebar WebviewViewProvider and the editor WebviewPanel.
 */
export function getWebviewContent(state: BackendState, port: number): string {
  switch (state.kind) {
    case 'checking':
      return wrapHtml('Checking', spinnerHtml('Checking AgentEye...'));

    case 'installing':
      return wrapHtml('Installing', spinnerHtml(state.message));

    case 'starting':
      return wrapHtml('Starting', spinnerHtml(`Starting AgentEye server... ${state.elapsed}s`));

    case 'connected':
      return connectedHtml(port);

    case 'reconnecting':
      return wrapHtml('Reconnecting', spinnerHtml('Reconnecting... trying again automatically'));

    case 'disconnected':
      return wrapHtml('Disconnected', `
        <div class="state-container">
          <span class="icon warning">⚠️</span>
          <h2>Server unreachable</h2>
          <p>The AgentEye server is not responding.</p>
          <button class="primary" onclick="action('retry')">Retry</button>
        </div>
      `);

    case 'error':
      return wrapHtml('Error', errorHtml(state));
  }
}

function connectedHtml(port: number): string {
  return `<!DOCTYPE html>
<html lang="en" style="height:100%;margin:0;padding:0">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; frame-src http://localhost:${port}; style-src 'unsafe-inline';">
  <style>
    html, body { height: 100%; margin: 0; padding: 0; overflow: hidden; }
    iframe { width: 100%; height: 100%; border: none; }
  </style>
</head>
<body>
  <iframe src="http://localhost:${port}"></iframe>
</body>
</html>`;
}

function errorHtml(state: BackendState & { kind: 'error' }): string {
  const isSetup = state.subtype === 'setup-required';
  const icon = isSetup ? 'ℹ️' : '❌';
  const iconClass = isSetup ? 'info' : 'error';

  let actions = '';
  switch (state.subtype) {
    case 'setup-required':
      actions = `
        <button class="primary" onclick="action('install')">Install</button>
        <button class="secondary" onclick="action('install-manually')">Install Manually</button>
      `;
      break;
    case 'no-python':
    case 'workspace-only-python':
    case 'configured-path-not-found':
    case 'configured-python-too-old':
      actions = `
        <button class="secondary" onclick="action('install-python')">Install Python</button>
        <button class="secondary" onclick="action('configure-path')">Configure Path</button>
        <button class="primary" onclick="action('retry')">Retry</button>
      `;
      break;
    case 'install-failed':
      actions = `
        <button class="secondary" onclick="action('view-terminal')">View Terminal</button>
        <button class="primary" onclick="action('retry')">Retry</button>
        <button class="secondary" onclick="action('install-manually')">Install Manually</button>
      `;
      break;
    case 'port-conflict':
      actions = `<button class="primary" onclick="action('retry')">Retry</button>`;
      break;
    case 'startup-failed':
      actions = `
        <button class="secondary" onclick="action('view-logs')">View Logs</button>
        <button class="primary" onclick="action('retry')">Retry</button>
      `;
      break;
  }

  return `
    <div class="state-container">
      <span class="icon ${iconClass}">${icon}</span>
      <h2>${isSetup ? 'Welcome to AgentEye!' : 'Something went wrong'}</h2>
      <p>${state.message}</p>
      <div class="actions">${actions}</div>
    </div>
  `;
}

function spinnerHtml(message: string): string {
  return `
    <div class="state-container">
      <div class="spinner"></div>
      <p>${message}</p>
    </div>
  `;
}

function wrapHtml(title: string, body: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
  <style>
    body {
      font-family: var(--vscode-font-family, system-ui);
      color: var(--vscode-foreground, #ccc);
      background: var(--vscode-editor-background, #1e1e1e);
      display: flex;
      justify-content: center;
      align-items: center;
      height: 100vh;
      margin: 0;
      padding: 16px;
      box-sizing: border-box;
    }
    .state-container {
      text-align: center;
      max-width: 400px;
    }
    .icon { font-size: 48px; display: block; margin-bottom: 16px; }
    h2 { margin: 0 0 8px; font-size: 18px; font-weight: 600; }
    p { margin: 0 0 16px; opacity: 0.8; font-size: 14px; }
    .actions { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
    button {
      padding: 6px 14px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 13px;
      font-family: inherit;
    }
    button.primary {
      background: var(--vscode-button-background, #0e639c);
      color: var(--vscode-button-foreground, #fff);
    }
    button.primary:hover { background: var(--vscode-button-hoverBackground, #1177bb); }
    button.secondary {
      background: var(--vscode-button-secondaryBackground, #3a3d41);
      color: var(--vscode-button-secondaryForeground, #ccc);
    }
    button.secondary:hover { background: var(--vscode-button-secondaryHoverBackground, #45494e); }
    .spinner {
      width: 32px; height: 32px;
      border: 3px solid var(--vscode-foreground, #ccc);
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin: 0 auto 16px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  ${body}
  <script>
    const vscode = acquireVsCodeApi();
    function action(cmd) { vscode.postMessage({ command: cmd }); }
  </script>
</body>
</html>`;
}

/**
 * Open the dashboard as a full-size editor tab
 */
export function openEditorPanel(
  backend: BackendManager,
  extensionUri: vscode.Uri,
): vscode.WebviewPanel {
  const panel = vscode.window.createWebviewPanel(
    'agenteye.editorDashboard',
    'AgentEye Dashboard',
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true },
  );

  const updatePanel = (state: BackendState) => {
    panel.webview.html = getWebviewContent(state, backend.port);
  };

  backend.onStateChange(updatePanel);
  updatePanel(backend.state);

  panel.webview.onDidReceiveMessage(msg => {
    switch (msg.command) {
      case 'retry':
        backend.activate();
        break;
      case 'install-python':
        vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/'));
        break;
      case 'configure-path':
        vscode.commands.executeCommand('workbench.action.openSettings', 'agenteye.pythonPath');
        break;
      case 'view-logs': {
        const logPath = process.platform === 'win32'
          ? `${process.env.USERPROFILE}\\.copilot\\logs\\agenteye.log`
          : `${process.env.HOME}/.copilot/logs/agenteye.log`;
        vscode.workspace.openTextDocument(vscode.Uri.file(logPath)).then(
          doc => vscode.window.showTextDocument(doc),
          () => vscode.window.showErrorMessage(`Log file not found: ${logPath}`),
        );
        break;
      }
      case 'install': {
        const terminal = vscode.window.createTerminal('AgentEye Install');
        terminal.show();
        terminal.sendText('pipx install agenteye-app');
        break;
      }
      case 'install-manually': {
        const manualTerminal = vscode.window.createTerminal('AgentEye Install');
        manualTerminal.show();
        // sendText with false = don't press Enter, user reviews first
        manualTerminal.sendText('pipx install agenteye-app', false);
        break;
      }
      case 'stop-backend':
        backend.stopBackend();
        break;
    }
  });

  return panel;
}
