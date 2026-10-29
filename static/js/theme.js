const KEY = "kept.theme";
export const MODES = ["system", "light", "dark"];

export function getTheme() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch (_) { return "system"; }
}

export function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") root.dataset.theme = mode;
  else delete root.dataset.theme;
  try { if (mode === "system") localStorage.removeItem(KEY); else localStorage.setItem(KEY, mode); } catch (_) { /* ignore */ }
  // Browser chrome colour follows the effective theme.
  const dark = mode === "dark" || (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.querySelectorAll('meta[name="theme-color"]').forEach((m) => { m.content = dark ? "#161826" : "#f5f6fa"; });
  window.dispatchEvent(new CustomEvent("kept:theme", { detail: mode }));
}

export function cycleTheme() {
  const next = MODES[(MODES.indexOf(getTheme()) + 1) % MODES.length];
  applyTheme(next);
  return next;
}
