import { useState, useEffect, useCallback } from 'react';
import { X, Search, RefreshCw, MessageSquare, Ban } from 'lucide-react';
import { fetchAnswers, fetchAnswer } from '../lib/api';

/**
 * Archive browser. Lists past Q&As filterable by date range + substring
 * search on query_text. Click-through loads the full record back into
 * the main view via `onSelect`.
 */
export default function ArchivePanel({ onClose, onSelect }) {
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [q, setQ] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchAnswers({ q, since, until, limit: 100 });
      setResults(data.results || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, since, until]);

  useEffect(() => {
    load();
  }, [load]);

  const handleOpen = async (requestId) => {
    try {
      const record = await fetchAnswer(requestId);
      onSelect(record);
      onClose();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 dark:bg-dark-800 light:bg-warm-50 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-6">
        {/* Header bar */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold dark:text-warm-100 light:text-dark-800">
            Archive
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              aria-label="Reload archive"
              className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            >
              <RefreshCw size={16} />
            </button>
            <button
              onClick={onClose}
              aria-label="Close archive"
              className="p-2 rounded-lg dark:text-dark-300 dark:hover:text-warm-200 dark:hover:bg-dark-600 light:text-warm-400 light:hover:text-dark-800 light:hover:bg-warm-100 transition-colors"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Filter row */}
        <div className="flex flex-wrap gap-2 mb-5">
          <div className="flex-1 min-w-[180px] relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 dark:text-dark-400 light:text-warm-400" />
            <input
              type="text"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search question text..."
              className="w-full pl-8 pr-3 py-1.5 text-sm rounded-md border
                dark:bg-dark-700 dark:border-dark-500 dark:text-warm-100 dark:placeholder-dark-400
                light:bg-white light:border-warm-300 light:text-dark-800 light:placeholder-warm-400"
            />
          </div>
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            aria-label="From date"
            className="px-2.5 py-1.5 text-sm rounded-md border
              dark:bg-dark-700 dark:border-dark-500 dark:text-warm-100
              light:bg-white light:border-warm-300 light:text-dark-800"
          />
          <input
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            aria-label="To date"
            className="px-2.5 py-1.5 text-sm rounded-md border
              dark:bg-dark-700 dark:border-dark-500 dark:text-warm-100
              light:bg-white light:border-warm-300 light:text-dark-800"
          />
        </div>

        {/* Body */}
        {loading && (
          <div className="dark:text-dark-300 light:text-warm-500 text-sm">Loading archive…</div>
        )}
        {error && (
          <div className="text-sm text-red-400 dark:bg-red-900/20 light:bg-red-100 px-3 py-2 rounded-md">
            {error}
          </div>
        )}
        {!loading && !error && results.length === 0 && (
          <div className="dark:text-dark-300 light:text-warm-500 text-sm italic">
            No archived answers match these filters.
          </div>
        )}

        <ul className="divide-y dark:divide-dark-600 light:divide-warm-200">
          {results.map((r) => (
            <li key={r.request_id}>
              <button
                onClick={() => handleOpen(r.request_id)}
                className="w-full text-left py-3 px-1 flex items-start gap-3
                  dark:hover:bg-dark-700 light:hover:bg-warm-100 transition-colors rounded"
              >
                <div className="shrink-0 mt-0.5">
                  {r.refused ? (
                    <Ban size={16} className="dark:text-amber-400 light:text-amber-600" />
                  ) : (
                    <MessageSquare size={16} className="dark:text-dark-300 light:text-warm-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium dark:text-warm-100 light:text-dark-800 truncate">
                    {r.query_text}
                  </div>
                  <div className="text-xs dark:text-dark-400 light:text-warm-500 mt-0.5 line-clamp-2">
                    {r.answer_preview}
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-xs dark:text-dark-400 light:text-warm-500">
                    <span>{formatTimestamp(r.timestamp)}</span>
                    {r.total_cost_usd != null && (
                      <span className="font-mono">${r.total_cost_usd.toFixed(4)}</span>
                    )}
                    {r.refused && (
                      <span className="px-1.5 py-0.5 rounded text-amber-700 dark:text-amber-300 dark:bg-amber-900/20 light:bg-amber-100">
                        refused
                      </span>
                    )}
                  </div>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function formatTimestamp(raw) {
  if (!raw) return '';
  try {
    const d = new Date(raw);
    return d.toLocaleString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return raw;
  }
}
