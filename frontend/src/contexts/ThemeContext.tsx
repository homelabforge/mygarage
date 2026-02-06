import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import axios from 'axios';

type Theme = 'light' | 'dark';

interface ThemeContextType {
  theme: Theme;
  toggleTheme: () => void;
  setTheme: (theme: Theme) => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export const useTheme = () => {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
};

interface ThemeProviderProps {
  children: React.ReactNode;
}

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }) => {
  const [theme, setThemeState] = useState<Theme>('dark');
  const [isInitialized, setIsInitialized] = useState(false);

  const applyTheme = useCallback((newTheme: Theme) => {
    const html = document.documentElement;
    if (newTheme === 'light') {
      html.classList.add('light');
      html.classList.remove('dark');
    } else {
      html.classList.add('dark');
      html.classList.remove('light');
    }
  }, []);

  // Initialize theme from localStorage and database
  useEffect(() => {
    let cancelled = false;

    const initializeTheme = async () => {
      // First, try to get theme from localStorage (instant)
      const localTheme = localStorage.getItem('theme') as Theme | null;
      if (localTheme === 'light' || localTheme === 'dark') {
        applyTheme(localTheme);
        setThemeState(localTheme);
      }

      // Then, sync with database (persistent across devices)
      // Use public endpoint for unauthenticated access (Security Enhancement v2.10.0)
      try {
        const response = await axios.get('/api/settings/public');
        if (cancelled) return;

        const settings = response.data.settings; // API returns { settings: [...], total: N }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const themeSetting = settings.find((s: any) => s.key === 'theme');

        if (themeSetting && themeSetting.value) {
          const dbTheme = themeSetting.value as Theme;
          if (dbTheme !== localTheme) {
            // Database has different value - use it
            applyTheme(dbTheme);
            setThemeState(dbTheme);
            localStorage.setItem('theme', dbTheme);
          }
        } else if (!localTheme) {
          // No theme set anywhere - use default dark
          applyTheme('dark');
          setThemeState('dark');
          localStorage.setItem('theme', 'dark');
        }
      } catch (error) {
        console.error('Failed to load theme from database:', error);
        // If database fails, keep localStorage value or default to dark
      }

      if (!cancelled) {
        setIsInitialized(true);
      }
    };

    initializeTheme();

    return () => { cancelled = true; };
  }, [applyTheme]);

  const setTheme = async (newTheme: Theme) => {
    // Apply immediately to DOM
    applyTheme(newTheme);
    setThemeState(newTheme);

    // Save to localStorage (instant persistence)
    localStorage.setItem('theme', newTheme);

    // Save to database (persistent across devices)
    try {
      await axios.put('/api/settings/theme', {
        key: 'theme',
        value: newTheme,
        category: 'general',
        description: 'User interface theme (light or dark)',
      });
    } catch (error) {
      console.error('Failed to save theme to database:', error);
      // Continue anyway - localStorage will work
    }
  };

  const toggleTheme = () => {
    const newTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
  };

  // Don't render children until theme is initialized to prevent flash
  if (!isInitialized) {
    return null;
  }

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
};
