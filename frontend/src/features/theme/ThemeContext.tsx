/* eslint-disable react-refresh/only-export-components -- provider + hook + pre-paint helpers co-located by design */
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

// Theme preference: an explicit choice or "follow the OS". The effective theme
// (light/dark) is applied as `data-theme` on <html>; styles.css keys off it.
export type ThemePref = 'light' | 'dark' | 'system';
export type Theme = 'light' | 'dark';

const KEY = 'spidey.theme';

function systemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function resolve(pref: ThemePref): Theme {
  return pref === 'system' ? systemTheme() : pref;
}

export function storedPref(): ThemePref {
  const value = localStorage.getItem(KEY);
  return value === 'light' || value === 'dark' || value === 'system' ? value : 'system';
}

// Called from main.tsx before render (from the app bundle, so it satisfies the
// strict CSP) to set the theme with no flash of the wrong palette.
export function applyTheme(pref: ThemePref): void {
  document.documentElement.dataset.theme = resolve(pref);
}

interface ThemeValue {
  pref: ThemePref;
  theme: Theme;
  setPref: (pref: ThemePref) => void;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(storedPref);
  const [theme, setTheme] = useState<Theme>(() => resolve(pref));

  useEffect(() => {
    setTheme(resolve(pref));
    applyTheme(pref);
    localStorage.setItem(KEY, pref);
  }, [pref]);

  // When following the OS, react to it changing live.
  useEffect(() => {
    if (pref !== 'system') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => {
      setTheme(systemTheme());
      applyTheme('system');
    };
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [pref]);

  const value = useMemo<ThemeValue>(
    () => ({
      pref,
      theme,
      setPref: setPrefState,
      toggle: () => setPrefState(theme === 'dark' ? 'light' : 'dark'),
    }),
    [pref, theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeValue {
  const value = useContext(ThemeContext);
  if (!value) throw new Error('useTheme must be used within ThemeProvider');
  return value;
}
