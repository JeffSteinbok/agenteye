import * as vscode from 'vscode';
import * as http from 'http';
import { spawn } from 'child_process';
import { resolveEnvironment, ResolvedEnvironment, ResolutionError } from './environment';

// Shared output channel for logging
let _outputChannel: vscode.OutputChannel | undefined;
function log(msg: string): void {
  if (!_outputChannel) {
    _outputChannel = vscode.window.createOutputChannel('AgentEye');
  }
  const ts = new Date().toISOString().slice(11, 23);
  _outputChannel.appendLine(`[${ts}] ${msg}`);
}

export type BackendState =
  | { kind: 'checking' }
  | { kind: 'installing'; message: string }
  | { kind: 'starting'; elapsed: number }
  | { kind: 'connected'; version: string; sessionCount: number }
  | { kind: 'reconnecting' }
  | { kind: 'disconnected' }
  | { kind: 'error'; subtype: ErrorSubtype; message: string };

export type ErrorSubtype =
  | 'setup-required'
  | 'no-python'
  | 'workspace-only-python'
  | 'configured-path-not-found'
  | 'configured-python-too-old'
  | 'install-failed'
  | 'port-conflict'
  | 'startup-failed';

interface HealthResponse {
  app?: string;
  version?: string;
  pid?: number;
  status?: string;
  [key: string]: unknown;
}

export class BackendManager {
  private _state: BackendState = { kind: 'checking' };
  private _onStateChange = new vscode.EventEmitter<BackendState>();
  readonly onStateChange = this._onStateChange.event;

  private _healthTimer: ReturnType<typeof setInterval> | undefined;
  private _consecutiveFailures = 0;
  private _wasConnected = false;
  private _disposed = false;
  private _resolvedEnv: ResolvedEnvironment | undefined;
  private _apiToken: string | undefined;

  get state(): BackendState {
    return this._state;
  }

  get port(): number {
    return vscode.workspace.getConfiguration('agenteye').get<number>('port', 5111);
  }

  private setState(state: BackendState): void {
    const prev = this._state.kind;
    this._state = state;
    if (prev !== state.kind) {
      log(`state: ${prev} → ${state.kind}${state.kind === 'connected' ? ` (v${state.version}, ${state.sessionCount} sessions)` : ''}`);
    }
    this._onStateChange.fire(state);
  }

  /** Main entry point — detect, start, connect */
  async activate(): Promise<void> {
    log('activate() called');
    this.setState({ kind: 'checking' });

    // Step 1: Try connecting to an already-running server FIRST
    log(`Step 1: health check on port ${this.port}`);
    const health = await this.healthCheck();
    log(`Step 1 result: ${health ? JSON.stringify(health) : 'null (no server)'}`);
    if (health) {
      await this.handleHealthSuccess(health);
      if (this._state.kind === 'connected') {
        this.startHealthMonitor();
        return;
      }
    }

    // Step 2: Resolve environment (needed for install/start)
    log('Step 2: resolving environment');
    const resolution = await resolveEnvironment();
    if (!resolution.ok) {
      log(`Step 2 FAILED: ${JSON.stringify(resolution.error)}`);
      this.setState(this.errorFromResolution(resolution.error));
      return;
    }

    this._resolvedEnv = resolution.env;
    log(`Step 2 OK: source=${resolution.env.source}, command=${resolution.env.command}, args=${JSON.stringify(resolution.env.args)}, agenteyeVersion=${resolution.env.agenteyeVersion ?? 'not found'}`);

    // Step 3: Check if agenteye module is available (for python-based)
    if (resolution.env.args.length > 0 && !resolution.env.agenteyeVersion) {
      log('Step 3: agenteye module not found in resolved Python — showing setup-required');
      this.setState({
        kind: 'error',
        subtype: 'setup-required',
        message: 'Welcome to AgentEye! The backend needs to be installed to get started.',
      });
      return;
    }

    // Step 4: No server running — start one
    log('Step 4: starting server');
    await this.startServer();
  }

  /** Start the backend server as a detached process */
  async startServer(): Promise<void> {
    if (!this._resolvedEnv) {
      const resolution = await resolveEnvironment();
      if (!resolution.ok) {
        this.setState(this.errorFromResolution(resolution.error));
        return;
      }
      this._resolvedEnv = resolution.env;
    }

    this.setState({ kind: 'starting', elapsed: 0 });
    const startTime = Date.now();
    const elapsedTimer = setInterval(() => {
      if (this._state.kind === 'starting') {
        this.setState({ kind: 'starting', elapsed: Math.floor((Date.now() - startTime) / 1000) });
      }
    }, 1000);

    const env = this._resolvedEnv;
    const port = this.port;

    try {
      // Launch detached process
      const allArgs = [...env.args, 'start', '--port', String(port)];
      const child = spawn(env.command, allArgs, {
        detached: true,
        stdio: 'ignore',
        windowsHide: true,
      });
      child.unref();

      // Poll for health with exponential backoff (500ms, 1s, 2s, 4s) up to 15s
      const backoffs = [500, 1000, 2000, 4000, 4000, 4000];
      let healthy = false;

      for (const delay of backoffs) {
        await sleep(delay);
        const health = await this.healthCheck();
        if (health) {
          await this.handleHealthSuccess(health);
          healthy = true;
          break;
        }
      }

      clearInterval(elapsedTimer);

      if (!healthy) {
        this.setState({
          kind: 'error',
          subtype: 'startup-failed',
          message: 'AgentEye server failed to start.',
        });
      }

      // Start health monitoring regardless (late starts can auto-recover)
      this.startHealthMonitor();
    } catch (err) {
      clearInterval(elapsedTimer);
      this.setState({
        kind: 'error',
        subtype: 'startup-failed',
        message: `Failed to launch AgentEye: ${err instanceof Error ? err.message : String(err)}`,
      });
    }
  }

  /** Periodic health monitoring */
  private startHealthMonitor(): void {
    this.stopHealthMonitor();
    const jitter = () => 10000 + (Math.random() * 4000 - 2000); // 10s ± 2s
    const poll = async () => {
      if (this._disposed) { return; }
      const health = await this.healthCheck();

      if (health) {
        if (this._state.kind === 'disconnected') {
          log('healthMonitor: server reachable — reconnecting');
          this.setState({ kind: 'reconnecting' });
          await sleep(1000);
          await this.handleHealthSuccess(health);
        } else if (this._state.kind !== 'connected') {
          await this.handleHealthSuccess(health);
        } else {
          // Update session count (keep existing version — no need to re-check PyPI every poll)
          const sessions = await this.fetchSessionCount();
          this.setState({
            kind: 'connected',
            version: this._state.kind === 'connected' ? this._state.version : 'unknown',
            sessionCount: sessions,
          });
        }
        this._consecutiveFailures = 0;
      } else {
        this._consecutiveFailures++;
        if (this._wasConnected && this._consecutiveFailures >= 3 && this._state.kind !== 'disconnected') {
          this._apiToken = undefined; // Token invalidated on disconnect
          this.setState({ kind: 'disconnected' });
        }
      }

      if (!this._disposed) {
        this._healthTimer = setTimeout(poll, jitter());
      }
    };

    this._healthTimer = setTimeout(poll, jitter());
  }

  private stopHealthMonitor(): void {
    if (this._healthTimer) {
      clearTimeout(this._healthTimer);
      this._healthTimer = undefined;
    }
  }

  /** Single health check — returns parsed response or null */
  async healthCheck(): Promise<HealthResponse | null> {
    const port = this.port;
    return new Promise(resolve => {
      const url = `http://localhost:${port}/api/health`;
      const req = http.get(url, { timeout: 3000 }, res => {
        if (res.statusCode === 401) {
          // AgentEye is running but requires auth — treat as detected
          resolve({ app: 'agenteye', status: 'running' });
          return;
        }
        if (res.statusCode !== 200) {
          resolve(null);
          return;
        }
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          try {
            resolve(JSON.parse(data));
          } catch {
            log(`healthCheck: JSON parse error on ${url}`);
            resolve(null);
          }
        });
      });
      req.on('error', () => resolve(null));
      req.on('timeout', () => { req.destroy(); resolve(null); });
    });
  }

  /** Fetch active session count from /api/processes (only running sessions) */
  private async fetchSessionCount(): Promise<number> {
    // Ensure we have a token for API auth
    if (!this._apiToken) {
      this._apiToken = await this.extractApiToken();
    }
    const url = this._apiToken
      ? `http://localhost:${this.port}/api/processes?token=${this._apiToken}`
      : `http://localhost:${this.port}/api/processes`;
    return new Promise(resolve => {
      const req = http.get(url, { timeout: 3000 }, res => {
        if (res.statusCode !== 200) {
          log(`fetchSessionCount: status=${res.statusCode}`);
          resolve(0);
          return;
        }
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          try {
            const processes = JSON.parse(data);
            resolve(typeof processes === 'object' ? Object.keys(processes).length : 0);
          } catch {
            resolve(0);
          }
        });
      });
      req.on('error', () => resolve(0));
      req.on('timeout', () => { req.destroy(); resolve(0); });
    });
  }

  /** Fetch server version from /api/version */
  private async fetchVersion(): Promise<string> {
    const token = this._apiToken;
    const url = token
      ? `http://localhost:${this.port}/api/version?token=${token}`
      : `http://localhost:${this.port}/api/version`;
    return new Promise(resolve => {
      const req = http.get(url, { timeout: 3000 }, res => {
        if (res.statusCode !== 200) { resolve('unknown'); return; }
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          try {
            const json = JSON.parse(data);
            resolve(json.current ?? 'unknown');
          } catch { resolve('unknown'); }
        });
      });
      req.on('error', () => resolve('unknown'));
      req.on('timeout', () => { req.destroy(); resolve('unknown'); });
    });
  }

  /** Fetch the root page and extract the API token from injected script */
  private async extractApiToken(): Promise<string | undefined> {
    return new Promise(resolve => {
      const req = http.get(`http://localhost:${this.port}/`, { timeout: 3000 }, res => {
        if (res.statusCode !== 200) {
          resolve(undefined);
          return;
        }
        let data = '';
        res.on('data', chunk => { data += chunk; });
        res.on('end', () => {
          const match = data.match(/window\.__DASHBOARD_TOKEN__\s*=\s*"([^"]+)"/);
          if (match) {
            log(`extractApiToken: token acquired (${match[1].slice(0, 8)}...)`);
            resolve(match[1]);
          } else {
            log('extractApiToken: token not found in root HTML');
            resolve(undefined);
          }
        });
      });
      req.on('error', () => resolve(undefined));
      req.on('timeout', () => { req.destroy(); resolve(undefined); });
    });
  }

  private async handleHealthSuccess(health: HealthResponse): Promise<void> {
    // Identity check
    if (health.app && health.app !== 'agenteye') {
      this.setState({
        kind: 'error',
        subtype: 'port-conflict',
        message: `Port ${this.port} is in use by another application.`,
      });
      return;
    }

    // Ensure we have auth before fetching version/sessions
    if (!this._apiToken) {
      this._apiToken = await this.extractApiToken();
    }
    const [sessions, version] = await Promise.all([
      this.fetchSessionCount(),
      this.fetchVersion(),
    ]);
    this._wasConnected = true;
    this._consecutiveFailures = 0;
    this.setState({
      kind: 'connected',
      version,
      sessionCount: sessions,
    });
  }

  private errorFromResolution(error: ResolutionError): BackendState {
    switch (error.kind) {
      case 'configured-path-not-found':
        return {
          kind: 'error', subtype: 'configured-path-not-found',
          message: `Configured Python path not found: ${error.path}`,
        };
      case 'configured-python-too-old':
        return {
          kind: 'error', subtype: 'configured-python-too-old',
          message: `Configured Python is ${error.version} (need 3.11+).`,
        };
      case 'workspace-only-python':
        return {
          kind: 'error', subtype: 'workspace-only-python',
          message: 'No system-level Python found. AgentEye requires a user-scoped Python (not a workspace virtualenv).',
        };
      case 'no-python':
        return {
          kind: 'error', subtype: 'no-python',
          message: 'Python 3.11+ is required to run AgentEye.',
        };
    }
  }

  /** Stop Backend command — with confirmation */
  async stopBackend(): Promise<void> {
    const choice = await vscode.window.showWarningMessage(
      'Stop the AgentEye server? This will disconnect all VS Code windows and the tray app using this server.',
      { modal: true },
      'Stop',
    );
    if (choice !== 'Stop') { return; }

    // Verify identity first
    const health = await this.healthCheck();
    if (!health) {
      vscode.window.showErrorMessage('Server is not responding. It may already be stopped.');
      this.setState({ kind: 'disconnected' });
      return;
    }
    if (health.app && health.app !== 'agenteye') {
      vscode.window.showErrorMessage(`The process on port ${this.port} is not AgentEye. Cannot stop.`);
      return;
    }

    // Try API shutdown first
    const stopped = await this.apiShutdown();
    if (stopped) {
      this.setState({ kind: 'disconnected' });
      return;
    }

    // Fallback: PID-based kill
    if (health.pid) {
      try {
        process.kill(health.pid, 'SIGTERM');
        await sleep(2000);
        try { process.kill(health.pid, 0); process.kill(health.pid, 'SIGKILL'); } catch { /* already dead */ }
      } catch { /* already dead */ }
      this.setState({ kind: 'disconnected' });
    } else {
      vscode.window.showErrorMessage('Cannot determine server PID. Stop it manually: agenteye stop');
    }
  }

  private async apiShutdown(): Promise<boolean> {
    return new Promise(resolve => {
      const req = http.request(
        { hostname: 'localhost', port: this.port, path: '/api/shutdown', method: 'POST', timeout: 5000 },
        res => { resolve(res.statusCode === 200); },
      );
      req.on('error', () => resolve(false));
      req.on('timeout', () => { req.destroy(); resolve(false); });
      req.end();
    });
  }

  /** Handle port setting change */
  onPortChanged(): void {
    this._consecutiveFailures = 0;
    this._wasConnected = false;
    this.stopHealthMonitor();
    vscode.window.showInformationMessage(`Port changed to ${this.port}. Reconnecting...`);
    this.activate();
  }

  dispose(): void {
    this._disposed = true;
    this.stopHealthMonitor();
    this._onStateChange.dispose();
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
