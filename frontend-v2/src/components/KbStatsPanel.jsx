import { useState, useEffect, useCallback } from 'react';
import { ChevronDown, ChevronRight, Database, FileText, Clock, FolderOpen } from 'lucide-react';
import { fetchKbStats } from '../lib/api';

const TOP_CATEGORIES_COUNT = 6;

function formatDate(isoString) {
  if (!isoString) return 'N/A';
  const d = new Date(isoString);
  return d.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }) + ', ' + d.toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function getTopCategories(chunkCountsByType) {
  if (!chunkCountsByType) return [];
  return Object.entries(chunkCountsByType)
    .sort((a, b) => b[1] - a[1])
    .slice(0, TOP_CATEGORIES_COUNT);
}

function getTotalDocs(docCountsByType) {
  if (!docCountsByType) return 0;
  return Object.values(docCountsByType).reduce((sum, n) => sum + n, 0);
}

export default function KbStatsPanel({ onOpenFilters }) {
  const storageKey = 'kbStatsPanelExpanded';
  const [expanded, setExpanded] = useState(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      return stored !== null ? JSON.parse(stored) : true;
    } catch {
      return true;
    }
  });
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchKbStats();
      setStats(data);
    } catch {
      // silently fail - stats are non-critical
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(expanded));
    } catch {
      // ignore
    }
  }, [expanded]);

  const toggleExpanded = () => setExpanded(prev => !prev);

  const totalDocs = stats ? getTotalDocs(stats.doc_counts_by_type) : 0;
  const topCategories = stats ? getTopCategories(stats.chunk_counts_by_type) : [];

  return (
    <div className="mb-4">
      {/* Header - always visible */}
      <button
        onClick={toggleExpanded}
        className="flex items-center gap-2 w-full text-left px-3 py-2.5 rounded-lg
          dark:hover:bg-dark-700 light:hover:bg-warm-100 transition-colors group"
      >
        <Database size={16} className="dark:text-accent light:text-accent-muted shrink-0" />
        <span className="text-sm font-medium dark:text-warm-100 light:text-dark-800 flex-1">
          Knowledge Base
        </span>
        {expanded ? (
          <ChevronDown size={14} className="dark:text-dark-400 light:text-warm-400" />
        ) : (
          <ChevronRight size={14} className="dark:text-dark-400 light:text-warm-400" />
        )}
      </button>

      {/* Expandable content */}
      <div
        className={`overflow-hidden transition-all duration-200 ease-in-out ${
          expanded ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'
        }`}
      >
        <div className="px-3 pt-1 pb-3">
          {loading && !stats ? (
            <div className="space-y-2 animate-pulse">
              <div className="h-3 w-24 rounded dark:bg-dark-600 light:bg-warm-200" />
              <div className="h-3 w-20 rounded dark:bg-dark-600 light:bg-warm-200" />
              <div className="h-3 w-28 rounded dark:bg-dark-600 light:bg-warm-200" />
            </div>
          ) : stats ? (
            <div className="space-y-3">
              {/* Key stats */}
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <Database size={12} className="dark:text-dark-400 light:text-warm-400" />
                  <span className="text-xs dark:text-warm-300 light:text-dark-600">
                    <span className="font-semibold font-mono">{stats.total_chunks?.toLocaleString()}</span> chunks
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <FileText size={12} className="dark:text-dark-400 light:text-warm-400" />
                  <span className="text-xs dark:text-warm-300 light:text-dark-600">
                    <span className="font-semibold font-mono">{totalDocs.toLocaleString()}</span> documents
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Clock size={12} className="dark:text-dark-400 light:text-warm-400" />
                  <span className="text-xs dark:text-warm-300 light:text-dark-600">
                    Updated: {formatDate(stats.last_refreshed)}
                  </span>
                </div>
              </div>

              {/* Top categories */}
              {topCategories.length > 0 && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <FolderOpen size={12} className="dark:text-dark-400 light:text-warm-400" />
                    <span className="text-xs font-medium dark:text-dark-300 light:text-warm-400">
                      Top Categories
                    </span>
                  </div>
                  <div className="space-y-0.5">
                    {topCategories.map(([name, count]) => (
                      <div key={name} className="flex items-center justify-between text-xs pl-5">
                        <span className="dark:text-warm-300 light:text-dark-600 truncate mr-2">
                          {name}
                        </span>
                        <span className="font-mono dark:text-dark-400 light:text-warm-400 shrink-0 tabular-nums">
                          {count.toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* View all link */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenFilters?.();
                }}
                className="text-xs dark:text-accent light:text-accent-muted hover:underline flex items-center gap-1 pl-0.5"
              >
                View all {stats.chunk_counts_by_type ? Object.keys(stats.chunk_counts_by_type).length : ''} categories
                <span aria-hidden="true">&rarr;</span>
              </button>
            </div>
          ) : (
            <p className="text-xs dark:text-dark-400 light:text-warm-400 italic">
              Unable to load KB stats
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
