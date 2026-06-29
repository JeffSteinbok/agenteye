/**
 * Hook to fetch and update dashboard settings (sync toggle) from the backend.
 */

import { useCallback, useEffect, useState } from "react";
import { fetchSettings, updateSettings } from "../api";
import type { DashboardSettings } from "../types";

const DEFAULT_SETTINGS: DashboardSettings = {
  sync_enabled: true,
  log_level: "INFO",
  mtime_active_threshold: 120,
};

export interface UseSettingsResult {
  settings: DashboardSettings;
  loading: boolean;
  setSyncEnabled: (enabled: boolean) => void;
  setLogLevel: (level: string) => void;
  setMtimeThreshold: (seconds: number) => void;
}

export function useSettings(): UseSettingsResult {
  const [settings, setSettings] = useState<DashboardSettings>(DEFAULT_SETTINGS);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const setSyncEnabled = useCallback((enabled: boolean) => {
    setSettings((prev) => ({ ...prev, sync_enabled: enabled }));
    updateSettings({ sync_enabled: enabled })
      .then(setSettings)
      .catch(() => {});
  }, []);

  const setLogLevel = useCallback((level: string) => {
    setSettings((prev) => ({ ...prev, log_level: level }));
    updateSettings({ log_level: level })
      .then(setSettings)
      .catch(() => {});
  }, []);

  const setMtimeThreshold = useCallback((seconds: number) => {
    setSettings((prev) => ({ ...prev, mtime_active_threshold: seconds }));
    updateSettings({ mtime_active_threshold: seconds })
      .then(setSettings)
      .catch(() => {});
  }, []);

  return { settings, loading, setSyncEnabled, setLogLevel, setMtimeThreshold };
}
