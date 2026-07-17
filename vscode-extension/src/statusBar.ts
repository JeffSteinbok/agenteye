import * as vscode from 'vscode';
import { BackendManager, BackendState } from './backend';

export class StatusBarManager {
  private _item: vscode.StatusBarItem;
  private _activated = false;

  constructor(
    private readonly _context: vscode.ExtensionContext,
    private readonly _backend: BackendManager,
  ) {
    this._item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    this._item.command = 'agenteye.openDashboard';

    // Restore visibility from global state
    this._activated = this._context.globalState.get<boolean>('agenteye.statusBarActivated', false);

    // Listen for state changes
    this._backend.onStateChange(state => this.update(state));
  }

  private update(state: BackendState): void {
    const showSetting = vscode.workspace.getConfiguration('agenteye').get<boolean>('showStatusBar', true);
    if (!showSetting) {
      this._item.hide();
      return;
    }

    switch (state.kind) {
      case 'connected':
        this._activated = true;
        this._context.globalState.update('agenteye.statusBarActivated', true);
        this._item.text = `$(eye) ${state.sessionCount} session${state.sessionCount !== 1 ? 's' : ''}`;
        this._item.tooltip = `AgentEye — ${state.sessionCount} active session${state.sessionCount !== 1 ? 's' : ''} (v${state.version})`;
        this._item.show();
        break;

      case 'disconnected':
        if (this._activated) {
          this._item.text = '$(warning) AgentEye';
          this._item.tooltip = 'AgentEye — server unreachable';
          this._item.show();
        }
        break;

      case 'reconnecting':
        if (this._activated) {
          this._item.text = '$(sync~spin) AgentEye';
          this._item.tooltip = 'AgentEye — reconnecting...';
          this._item.show();
        }
        break;

      case 'checking':
      case 'starting':
      case 'installing':
        if (this._activated) {
          this._item.text = '$(loading~spin) AgentEye';
          this._item.tooltip = 'AgentEye — connecting...';
          this._item.show();
        }
        break;

      case 'error':
        if (this._activated) {
          this._item.text = '$(warning) AgentEye';
          this._item.tooltip = `AgentEye — ${state.message}`;
          this._item.show();
        }
        break;
    }
  }

  dispose(): void {
    this._item.dispose();
  }
}
