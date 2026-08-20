import { createContext, useContext } from 'react';
import { Platform } from 'react-native';

// Broadsheet — single theme, transcribed from
// src/design_handoff_balanceai_chat/broadsheet.css (source of truth for values).
export const BROADSHEET = {
  id: 'broadsheet',
  name: 'BROADSHEET',

  bg: '#f3f2f2',
  surface: '#eae9e9',
  text: '#201e1d',
  divider: 'rgba(32,30,29,0.16)',
  rowHairline: 'rgba(32,30,29,0.08)',

  accent: '#0088b0',
  accent2: '#d6006c',

  neutral: {
    100: '#f8f4f4', 200: '#eae7e7', 300: '#d7d3d3', 400: '#bab6b6', 500: '#9b9797',
    600: '#7d7979', 700: '#605d5d', 800: '#444141', 900: '#2d2b2b',
  },
  accentRamp: {
    100: '#e9f8ff', 200: '#cbeeff', 300: '#99e0ff', 400: '#62c5ee', 500: '#38a6cf',
    600: '#1186ac', 700: '#006786', 800: '#004961', 900: '#0a303e',
  },
  accent2Ramp: {
    100: '#fff1f4', 200: '#ffdee6', 300: '#ffc0d0', 400: '#ff90b1', 500: '#ff458e',
    600: '#d82071', 700: '#aa0b56', 800: '#790e3d', 900: '#4b1528',
  },

  // Semantic aliases used across screens.
  danger: '#d93025',
  success: '#1a7a4a',
  warn: '#b06a00',

  // Source Serif 4 for everything — headings/figures at 600, body at 400,
  // true italic for emphasis. No sans-serif anywhere, including chrome.
  fontHeading: 'SourceSerif4_600SemiBold',
  fontBody: 'SourceSerif4_400Regular',
  fontBodyItalic: 'SourceSerif4_400Regular_Italic',
  // Used only for placeholder-swatch captions (receipt/viewfinder labels) —
  // not part of the type system proper.
  monoLabel: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'ui-monospace, Menlo, monospace' }),

  space: { 1: 5, 2: 10, 3: 15, 4: 20, 6: 30, 8: 40 },
  radius: { sm: 1, md: 2, lg: 4 },

  shadowSm: { shadowColor: '#2d2b2b', shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.14, shadowRadius: 2, elevation: 2 },
  shadowMd: { shadowColor: '#2d2b2b', shadowOffset: { width: 0, height: 3 }, shadowOpacity: 0.16, shadowRadius: 10, elevation: 4 },
  shadowLg: { shadowColor: '#2d2b2b', shadowOffset: { width: 0, height: 12 }, shadowOpacity: 0.22, shadowRadius: 32, elevation: 10 },
};

export const ThemeContext = createContext(BROADSHEET);
export const useTheme = () => useContext(ThemeContext);
