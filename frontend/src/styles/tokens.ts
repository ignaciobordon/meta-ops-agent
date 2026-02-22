/**
 * Mediterranean Deluxe Design System Tokens
 */

export const tokens = {
  colors: {
    // Palette
    sand: {
      50: '#FDFCFB',
      100: '#F9F7F4',
      200: '#F3EFE9',
      300: '#E8E1D5',
      500: '#D4C4B0',
      700: '#A89478',
    },
    terracotta: {
      100: '#F7E4D9',
      300: '#E8B89A',
      500: '#D4845C',
      700: '#B86637',
      900: '#8A3F1F',
    },
    olive: {
      100: '#E8EDD5',
      300: '#C5D49A',
      500: '#8B9D5D',
      700: '#6B7B3F',
    },
    navy: {
      700: '#2C3E50',
      900: '#1A252F',
    },
    stone: {
      200: '#E6DED3',
      300: '#D1C4B5',
      400: '#B8A894',
    },
    gold: {
      500: '#D4AF37',
    },

    // Semantic
    background: '#F9F7F4',
    surface: '#FFFFFF',
    border: '#E6DED3',
    text: {
      primary: '#2C3E50',
      secondary: '#6B7B3F',
      muted: '#A89478',
    },
    state: {
      success: '#8B9D5D',
      warning: '#D4AF37',
      error: '#B86637',
      info: '#6B7B3F',
    },
  },

  spacing: {
    xs: '4px',
    sm: '8px',
    md: '16px',
    lg: '24px',
    xl: '32px',
    '2xl': '48px',
    '3xl': '64px',
  },

  radius: {
    sm: '4px',
    md: '8px',
    lg: '12px',
    xl: '16px',
    '2xl': '24px',
    full: '9999px',
  },

  shadows: {
    sm: '0 1px 2px rgba(44, 62, 80, 0.04)',
    md: '0 4px 8px rgba(44, 62, 80, 0.06)',
    lg: '0 8px 16px rgba(44, 62, 80, 0.08)',
    xl: '0 16px 32px rgba(44, 62, 80, 0.12)',
  },

  typography: {
    fontFamily: {
      display: '"Newsreader", "Georgia", serif',
      body: '"Inter", "Helvetica Neue", sans-serif',
      mono: '"JetBrains Mono", "Courier New", monospace',
    },
  },
};

// State color mapping
export const stateColors: Record<string, string> = {
  draft: tokens.colors.stone[400],
  validating: tokens.colors.gold[500],
  ready: tokens.colors.olive[500],
  blocked: tokens.colors.terracotta[700],
  pending_approval: tokens.colors.gold[500],
  approved: tokens.colors.olive[500],
  rejected: tokens.colors.terracotta[700],
  executing: tokens.colors.gold[500],
  executed: tokens.colors.olive[500],
  failed: tokens.colors.terracotta[700],
  rolled_back: tokens.colors.stone[400],
  expired: tokens.colors.stone[400],
};
