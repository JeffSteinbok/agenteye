import * as vscode from 'vscode';
import { execFile } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';
import * as fs from 'fs';

const execFileAsync = promisify(execFile);

export interface ResolvedEnvironment {
  /** The command to launch agenteye (binary path or python path) */
  command: string;
  /** Arguments to pass (e.g., ['-m', 'agenteye'] for python-based) */
  args: string[];
  /** How the environment was resolved — determines install/upgrade commands */
  source: 'setting-binary' | 'setting-python' | 'path-binary' | 'vscode-python' | 'system-python';
  /** Python version if resolved via interpreter */
  pythonVersion?: string;
  /** AgentEye version if already installed */
  agenteyeVersion?: string;
}

export type ResolutionError =
  | { kind: 'configured-path-not-found'; path: string }
  | { kind: 'configured-python-too-old'; path: string; version: string }
  | { kind: 'workspace-only-python' }
  | { kind: 'no-python' };

export type ResolutionResult =
  | { ok: true; env: ResolvedEnvironment }
  | { ok: false; error: ResolutionError };

const MIN_PYTHON_MAJOR = 3;
const MIN_PYTHON_MINOR = 11;

export async function resolveEnvironment(): Promise<ResolutionResult> {
  // Step 1: Extension setting (highest priority)
  const configuredPath = vscode.workspace.getConfiguration('agenteye').get<string>('pythonPath', '').trim();
  if (configuredPath) {
    return resolveConfiguredPath(configuredPath);
  }

  // Step 2: agenteye on PATH
  const pathBinary = await findOnPath('agenteye');
  if (pathBinary) {
    const version = await getAgenteyeVersion(pathBinary, []);
    if (version) {
      return {
        ok: true,
        env: { command: pathBinary, args: [], source: 'path-binary', agenteyeVersion: version },
      };
    }
  }

  // Step 3: VS Code Python extension interpreter (skip workspace-scoped venvs)
  const vscodePython = vscode.workspace.getConfiguration('python').get<string>('defaultInterpreterPath', '').trim();
  if (vscodePython && !isWorkspaceScopedVenv(vscodePython)) {
    const pyResult = await validatePython(vscodePython);
    if (pyResult.ok) {
      const aeVersion = await getAgenteyeVersion(vscodePython, ['-m', 'agenteye']);
      return {
        ok: true,
        env: {
          command: vscodePython, args: ['-m', 'agenteye'], source: 'vscode-python',
          pythonVersion: pyResult.version ?? undefined, agenteyeVersion: aeVersion ?? undefined,
        },
      };
    }
  }

  // Track if we skipped a workspace venv (for error messaging)
  const skippedWorkspaceVenv = vscodePython && isWorkspaceScopedVenv(vscodePython);

  // Step 4-5: python3 / python on PATH
  for (const cmd of ['python3', 'python']) {
    const pyPath = await findOnPath(cmd);
    if (pyPath) {
      const pyResult = await validatePython(pyPath);
      if (pyResult.ok) {
        const aeVersion = await getAgenteyeVersion(pyPath, ['-m', 'agenteye']);
        return {
          ok: true,
          env: {
            command: pyPath, args: ['-m', 'agenteye'], source: 'system-python',
            pythonVersion: pyResult.version ?? undefined, agenteyeVersion: aeVersion ?? undefined,
          },
        };
      }
    }
  }

  // Nothing found
  if (skippedWorkspaceVenv) {
    return { ok: false, error: { kind: 'workspace-only-python' } };
  }
  return { ok: false, error: { kind: 'no-python' } };
}

async function resolveConfiguredPath(configuredPath: string): Promise<ResolutionResult> {
  // Check if file exists
  if (!fs.existsSync(configuredPath)) {
    return { ok: false, error: { kind: 'configured-path-not-found', path: configuredPath } };
  }

  // Try as agenteye binary first
  const aeVersion = await getAgenteyeVersion(configuredPath, []);
  if (aeVersion) {
    return {
      ok: true,
      env: { command: configuredPath, args: [], source: 'setting-binary', agenteyeVersion: aeVersion },
    };
  }

  // Try as Python interpreter
  const pyResult = await validatePython(configuredPath);
  if (pyResult.ok) {
    const aeVer = await getAgenteyeVersion(configuredPath, ['-m', 'agenteye']);
    return {
      ok: true,
      env: {
        command: configuredPath, args: ['-m', 'agenteye'], source: 'setting-python' as const,
        pythonVersion: pyResult.version ?? undefined, agenteyeVersion: aeVer ?? undefined,
      },
    };
  }

  if (pyResult.version) {
    return { ok: false, error: { kind: 'configured-python-too-old', path: configuredPath, version: pyResult.version } };
  }

  return { ok: false, error: { kind: 'configured-path-not-found', path: configuredPath } };
}

/** Get the install command for a given resolution source */
export function getInstallCommand(env: ResolvedEnvironment): { command: string; args: string[] } | null {
  switch (env.source) {
    case 'setting-python':
    case 'vscode-python':
    case 'system-python':
      return { command: env.command, args: ['-m', 'pip', 'install', 'agenteye-app'] };
    case 'path-binary':
    case 'setting-binary':
      // Can't pip-install into a binary — user must upgrade manually or use pipx
      return null;
  }
}

/** Get the upgrade command for a given resolution source */
export function getUpgradeCommand(env: ResolvedEnvironment): { command: string; args: string[] } | null {
  switch (env.source) {
    case 'setting-python':
    case 'vscode-python':
    case 'system-python':
      return { command: env.command, args: ['-m', 'pip', 'install', '--upgrade', 'agenteye-app'] };
    case 'path-binary':
    case 'setting-binary':
      return null;
  }
}

/** Get a human-readable install command string for "Install Manually" */
export function getManualInstallHint(env: ResolvedEnvironment): string {
  switch (env.source) {
    case 'setting-python':
    case 'vscode-python':
    case 'system-python':
      return `${env.command} -m pip install agenteye-app`;
    case 'path-binary':
    case 'setting-binary':
      return 'pipx upgrade agenteye-app';
  }
}

function isWorkspaceScopedVenv(pythonPath: string): boolean {
  const normalized = pythonPath.replace(/\\/g, '/').toLowerCase();
  const venvPatterns = ['/venv/', '/.venv/', '/env/'];
  if (venvPatterns.some(p => normalized.includes(p))) {
    return true;
  }
  // Check if path is inside any workspace folder
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders) {
    for (const folder of workspaceFolders) {
      const folderPath = folder.uri.fsPath.replace(/\\/g, '/').toLowerCase();
      if (normalized.startsWith(folderPath + '/')) {
        return true;
      }
    }
  }
  return false;
}

async function findOnPath(name: string): Promise<string | null> {
  const cmd = process.platform === 'win32' ? 'where' : 'which';
  try {
    const { stdout } = await execFileAsync(cmd, [name], { timeout: 5000 });
    const firstLine = stdout.trim().split(/\r?\n/)[0];
    return firstLine || null;
  } catch {
    return null;
  }
}

async function validatePython(pythonPath: string): Promise<{ ok: boolean; version: string | null }> {
  try {
    const { stdout } = await execFileAsync(pythonPath, ['--version'], { timeout: 5000 });
    const match = stdout.trim().match(/Python (\d+)\.(\d+)\.(\d+)/);
    if (!match) {
      return { ok: false, version: null };
    }
    const major = parseInt(match[1], 10);
    const minor = parseInt(match[2], 10);
    const version = `${match[1]}.${match[2]}.${match[3]}`;
    const ok = major > MIN_PYTHON_MAJOR || (major === MIN_PYTHON_MAJOR && minor >= MIN_PYTHON_MINOR);
    return { ok, version };
  } catch {
    return { ok: false, version: null };
  }
}

async function getAgenteyeVersion(command: string, baseArgs: string[]): Promise<string | null> {
  try {
    const { stdout } = await execFileAsync(command, [...baseArgs, '--version'], { timeout: 5000 });
    const match = stdout.trim().match(/(\d+\.\d+\.\d+)/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}
