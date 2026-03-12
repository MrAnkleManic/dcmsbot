import { Settings, Sun, Moon, Activity } from 'lucide-react';

export default function Header({ theme, toggleTheme, onOpenSettings, onOpenKbHealth }) {
  return (
    <header className="border-b border-dark-600 dark:border-dark-600 light:border-warm-300">
      <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight dark:text-warm-100 light:text-dark-800">
            DCMS Evidence Bot
          </h1>
          <p className="text-sm dark:text-dark-300 light:text-warm-400 mt-0.5">
            Expert answers on the Online Safety Act
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            aria-label="Toggle theme"
          >
            {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <button
            onClick={onOpenKbHealth}
            className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            aria-label="KB Health"
            title="KB Health Dashboard"
          >
            <Activity size={18} />
          </button>
          <button
            onClick={onOpenSettings}
            className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            aria-label="Settings"
          >
            <Settings size={18} />
          </button>
        </div>
      </div>
    </header>
  );
}
