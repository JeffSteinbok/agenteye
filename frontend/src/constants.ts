/**
 * Centralised constants for the Copilot Dashboard frontend.
 *
 * All magic numbers, polling intervals, localStorage keys, and
 * lookup tables live here so they are easy to find, tune, and test.
 */

// ── Polling & timing (milliseconds) ────────────────────────────────────────

/**
 * Fast poll for process state (working/thinking/waiting/idle) while the
 * dashboard tab is visible. Kept low for snappy, near-real-time updates.
 */
export const PROCESS_POLL_MS = 1_000;

/** Full session + process refetch interval while the tab is visible. */
export const SESSION_POLL_MS = 15_000;

/**
 * Slow process poll used only while the tab is hidden, purely to keep desktop
 * notifications firing for state transitions. Disabled when notifications are
 * off (nothing to do in the background).
 */
export const BACKGROUND_POLL_MS = 5_000;

/** How often to re-check PyPI for a new version. */
export const VERSION_CHECK_MS = 30 * 60 * 1_000;

/** Timeout while waiting for the server to come back after an update. */
export const UPDATE_POLL_TIMEOUT_MS = 90_000;

/** Interval between pings while waiting for a server update. */
export const UPDATE_POLL_INTERVAL_MS = 2_000;

/** Delay before a tooltip appears on hover. */
export const TOOLTIP_DELAY_MS = 400;

/** Duration of the "✓ copied" feedback on copy buttons. */
export const COPY_FEEDBACK_MS = 1_200;

/** Disconnect retry countdown start value (seconds, not ms). */
export const RETRY_COUNTDOWN_SECONDS = 5;

/** Tick interval for the retry countdown. */
export const RETRY_TICK_MS = 1_000;

// ── Thresholds ─────────────────────────────────────────────────────────────

/** Consecutive fetch failures before showing the disconnect overlay. */
export const DISCONNECT_THRESHOLD = 2;

/** Sessions older than this are excluded from the "Previous" tab (ms). */
export const PREVIOUS_SESSION_WINDOW_MS = 5 * 24 * 60 * 60 * 1_000;

// ── localStorage keys ──────────────────────────────────────────────────────

export const STORAGE_KEY_MODE = "dash-mode";
export const STORAGE_KEY_PALETTE = "dash-palette";
export const STORAGE_KEY_VIEW = "dash-view";
export const STORAGE_KEY_STARRED = "dash-starred";
export const STORAGE_KEY_WIDGETS_COLLAPSED = "dash-widgets-collapsed";
export const STORAGE_KEY_GROUP_BY = "dash-group-by";

// ── Theme options ──────────────────────────────────────────────────────────

export const THEME_MODES = ["dark", "light"] as const;
export const THEME_PALETTES = [
  "default",
  "pink",
  "ocean",
  "forest",
  "sunset",
  "mono",
  "neon",
  "slate",
  "rosegold",
] as const;

/** Emoji-labelled palette options for the UI selector, derived from THEME_PALETTES. */
const PALETTE_EMOJI: Record<string, string> = {
  default: "🌈",
  pink: "🌸",
  ocean: "🌊",
  forest: "🌳",
  sunset: "🌅",
  mono: "⚫",
  neon: "⚡",
  slate: "🩶",
  rosegold: "💫",
};

export const PALETTE_OPTIONS: { value: (typeof THEME_PALETTES)[number]; label: string }[] =
  THEME_PALETTES.map((p) => ({
    value: p,
    label: `${PALETTE_EMOJI[p] ?? ""} ${p.charAt(0).toUpperCase() + p.slice(1)}`,
  }));

// ── State display labels & CSS mappings ────────────────────────────────────

/** Human-readable labels for session states. */
export const STATE_LABELS: Record<string, string> = {
  waiting: "⏳ Waiting",
  working: "⚒️ Working",
  thinking: "🤔 Thinking",
  idle: "🔵 Idle",
  unknown: "",
};

/** CSS class for state badges. */
export const STATE_BADGE_CLASS: Record<string, string> = {
  waiting: "badge-waiting",
  working: "badge-working",
  thinking: "badge-thinking",
  idle: "badge-idle",
  unknown: "badge-active",
};

/** CSS class for tile cards by state. */
export const TILE_STATE_CLASS: Record<string, string> = {
  waiting: "waiting-tile",
  working: "active-tile",
  thinking: "active-tile",
  idle: "idle-tile",
  unknown: "",
};

// ── Z-index layers ─────────────────────────────────────────────────────────

export const Z_TOOLTIP = 9998;
export const Z_DISCONNECT_OVERLAY = 9999;
