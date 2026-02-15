---
name: theme-factory
description: "Generate color themes and design systems. Use when creating consistent visual styles."
allowed-tools: "Read,Write"
version: 1.0.0
---

# Theme Factory

## Color Palette Generator
```typescript
interface Theme {
  colors: {
    primary: string;
    secondary: string;
    accent: string;
    background: string;
    surface: string;
    text: string;
    textMuted: string;
    border: string;
    error: string;
    success: string;
    warning: string;
  };
  fonts: {
    heading: string;
    body: string;
    mono: string;
  };
  spacing: number[];
  radii: { sm: string; md: string; lg: string; full: string };
}
```

## Generate from Primary Color
```typescript
import chroma from 'chroma-js';

function generateTheme(primaryHex: string): Theme {
  const primary = chroma(primaryHex);
  
  return {
    colors: {
      primary: primaryHex,
      secondary: primary.set('hsl.h', '+180').hex(),
      accent: primary.set('hsl.h', '+30').hex(),
      background: '#ffffff',
      surface: '#f8f9fa',
      text: '#212529',
      textMuted: '#6c757d',
      border: '#dee2e6',
      error: '#dc3545',
      success: '#28a745',
      warning: '#ffc107'
    },
    fonts: {
      heading: 'Inter, sans-serif',
      body: 'Inter, sans-serif',
      mono: 'JetBrains Mono, monospace'
    },
    spacing: [0, 4, 8, 16, 24, 32, 48, 64],
    radii: { sm: '4px', md: '8px', lg: '16px', full: '9999px' }
  };
}
```

## CSS Variables Output
```typescript
function themeToCSSVars(theme: Theme): string {
  return `
:root {
  --color-primary: ${theme.colors.primary};
  --color-secondary: ${theme.colors.secondary};
  --color-background: ${theme.colors.background};
  --font-heading: ${theme.fonts.heading};
  --font-body: ${theme.fonts.body};
}`;
}
```
