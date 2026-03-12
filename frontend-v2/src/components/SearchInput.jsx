import { Search, Loader2, RotateCcw } from 'lucide-react';
import { useState } from 'react';

export default function SearchInput({ onSubmit, isLoading, hasHistory, onNewConversation }) {
  const [query, setQuery] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed.length >= 3 && !isLoading) {
      onSubmit(trimmed);
    }
  };

  return (
    <div className="w-full space-y-2">
      <form onSubmit={handleSubmit} className="w-full">
        <div className="relative">
          <div className="absolute left-4 top-1/2 -translate-y-1/2 dark:text-dark-300 light:text-warm-400">
            {isLoading ? (
              <Loader2 size={20} className="animate-spin" />
            ) : (
              <Search size={20} />
            )}
          </div>
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={hasHistory
              ? "Ask a follow-up question..."
              : "Ask a question about the Online Safety Act..."}
            disabled={isLoading}
            className="w-full pl-12 pr-4 py-4 rounded-xl text-base
              dark:bg-dark-700 dark:text-warm-100 dark:placeholder-dark-400 dark:border-dark-500 dark:focus:border-accent
              light:bg-white light:text-dark-800 light:placeholder-warm-400 light:border-warm-300 light:focus:border-accent
              border outline-none transition-colors disabled:opacity-50"
          />
        </div>
      </form>

      {hasHistory && onNewConversation && (
        <button
          type="button"
          onClick={onNewConversation}
          disabled={isLoading}
          className="flex items-center gap-1.5 text-xs
            dark:text-dark-300 dark:hover:text-warm-200
            light:text-warm-500 light:hover:text-warm-700
            transition-colors disabled:opacity-50"
        >
          <RotateCcw size={12} />
          New conversation
        </button>
      )}
    </div>
  );
}
