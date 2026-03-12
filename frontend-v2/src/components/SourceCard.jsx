import { ChevronDown, ChevronRight, ChevronLeft, ExternalLink, Loader2, ArrowUp } from 'lucide-react';
import { useState } from 'react';
import { toSuperscript } from '../lib/citations';
import { fetchChunk } from '../lib/api';

const typeColors = {
  'Act': 'bg-blue-900/30 text-blue-300 light:bg-blue-100 light:text-blue-800',
  'Act of Parliament': 'bg-blue-900/30 text-blue-300 light:bg-blue-100 light:text-blue-800',
  'Guidance': 'bg-emerald-900/30 text-emerald-300 light:bg-emerald-100 light:text-emerald-800',
  'Ofcom Guidance': 'bg-emerald-900/30 text-emerald-300 light:bg-emerald-100 light:text-emerald-800',
  'Explanatory Notes': 'bg-purple-900/30 text-purple-300 light:bg-purple-100 light:text-purple-800',
  'Debates': 'bg-amber-900/30 text-amber-300 light:bg-amber-100 light:text-amber-800',
  'Hansard': 'bg-amber-900/30 text-amber-300 light:bg-amber-100 light:text-amber-800',
  'Lords Debate': 'bg-amber-900/30 text-amber-300 light:bg-amber-100 light:text-amber-800',
  'Commons Debate': 'bg-amber-900/30 text-amber-300 light:bg-amber-100 light:text-amber-800',
};

function getTypeBadgeClass(type) {
  return typeColors[type] || 'bg-gray-900/30 text-gray-300 light:bg-gray-100 light:text-gray-700';
}

export default function SourceCard({ citation, index, hasReturnAnchor, onBackToText }) {
  const [expanded, setExpanded] = useState(false);
  const [adjacentChunks, setAdjacentChunks] = useState([]); // stack of loaded chunks
  const [loadingDirection, setLoadingDirection] = useState(null); // 'prev' | 'next' | null
  const num = index + 1;

  // The current "view" — the original excerpt plus any loaded adjacent chunks
  const currentChunk = adjacentChunks.length > 0
    ? adjacentChunks[adjacentChunks.length - 1]
    : null;

  const hasPrev = currentChunk ? !!currentChunk.prev_chunk_id : !!citation.prev_chunk_id;
  const hasNext = currentChunk ? !!currentChunk.next_chunk_id : !!citation.next_chunk_id;

  const loadAdjacentChunk = async (direction) => {
    const chunkId = direction === 'prev'
      ? (currentChunk?.prev_chunk_id || citation.prev_chunk_id)
      : (currentChunk?.next_chunk_id || citation.next_chunk_id);

    if (!chunkId) return;

    setLoadingDirection(direction);
    try {
      const chunk = await fetchChunk(chunkId);
      setAdjacentChunks(prev => [...prev, chunk]);
    } catch (err) {
      console.error('Failed to load adjacent chunk:', err);
    } finally {
      setLoadingDirection(null);
    }
  };

  const handleGoBack = () => {
    setAdjacentChunks(prev => prev.slice(0, -1));
  };

  const displayText = currentChunk?.chunk_text || citation.excerpt;
  const displayHeader = currentChunk?.header || citation.location_pointer;

  return (
    <div
      id={`source-${citation.citation_id}`}
      className="rounded-lg border transition-all duration-300
        dark:bg-dark-700 dark:border-dark-500 dark:hover:border-dark-400
        light:bg-white light:border-warm-300 light:hover:border-warm-400"
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3 flex items-start gap-3"
      >
        <span className="text-accent font-medium text-sm mt-0.5 shrink-0 w-5 text-right">
          {toSuperscript(num)}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm dark:text-warm-100 light:text-dark-800 truncate">
              {citation.title}
            </span>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${getTypeBadgeClass(citation.source_type)}`}>
              {citation.source_type}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-1 text-xs dark:text-dark-300 light:text-warm-400">
            {citation.location_pointer && <span>{citation.location_pointer}</span>}
            {citation.date_published && <span>{citation.date_published}</span>}
            {citation.source_format && (
              <span className="opacity-60" title="Source document format">
                {citation.source_format}
              </span>
            )}
          </div>
        </div>
        <span className="dark:text-dark-400 light:text-warm-400 mt-0.5 shrink-0">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 pl-12">
          {/* Navigation header when viewing adjacent chunks */}
          {adjacentChunks.length > 0 && (
            <div className="flex items-center gap-2 mb-2">
              <button
                onClick={handleGoBack}
                className="text-xs flex items-center gap-1 px-2 py-1 rounded
                  dark:text-accent dark:hover:text-accent-light dark:bg-dark-600
                  light:text-accent light:hover:text-accent-light light:bg-warm-100
                  transition-colors"
              >
                ← Back{adjacentChunks.length > 1 ? ` (${adjacentChunks.length} deep)` : ''}
              </button>
              {displayHeader && displayHeader !== citation.location_pointer && (
                <span className="text-xs dark:text-dark-300 light:text-warm-400 italic">
                  {displayHeader}
                </span>
              )}
            </div>
          )}

          {/* Excerpt text */}
          <div className="text-sm leading-relaxed dark:text-warm-300 light:text-dark-700 dark:bg-dark-600/50 light:bg-warm-50 rounded-lg p-3 border dark:border-dark-500 light:border-warm-200">
            {displayText}
          </div>

          {/* Adjacent chunk navigation buttons */}
          {(hasPrev || hasNext) && (
            <div className="flex items-center gap-2 mt-2">
              {hasPrev && (
                <button
                  onClick={() => loadAdjacentChunk('prev')}
                  disabled={loadingDirection !== null}
                  className="text-xs flex items-center gap-1 px-2.5 py-1 rounded
                    dark:text-dark-300 dark:hover:text-warm-200 dark:bg-dark-600 dark:hover:bg-dark-500
                    light:text-warm-500 light:hover:text-warm-600 light:bg-warm-100 light:hover:bg-warm-200
                    border dark:border-dark-500 light:border-warm-300
                    transition-colors disabled:opacity-50"
                >
                  {loadingDirection === 'prev' ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <ChevronLeft size={12} />
                  )}
                  Previous section
                </button>
              )}
              {hasNext && (
                <button
                  onClick={() => loadAdjacentChunk('next')}
                  disabled={loadingDirection !== null}
                  className="text-xs flex items-center gap-1 px-2.5 py-1 rounded
                    dark:text-dark-300 dark:hover:text-warm-200 dark:bg-dark-600 dark:hover:bg-dark-500
                    light:text-warm-500 light:hover:text-warm-600 light:bg-warm-100 light:hover:bg-warm-200
                    border dark:border-dark-500 light:border-warm-300
                    transition-colors disabled:opacity-50"
                >
                  Next section
                  {loadingDirection === 'next' ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <ChevronRight size={12} />
                  )}
                </button>
              )}
            </div>
          )}

          {/* Publisher, source URL, and back-to-text */}
          <div className="flex items-center justify-between mt-2 flex-wrap gap-2">
            <div className="flex items-center gap-3">
              {citation.publisher && (
                <p className="text-xs dark:text-dark-300 light:text-warm-400">
                  {citation.publisher}
                </p>
              )}
              {citation.source_url && citation.source_url.trim() !== '' && (
                <a
                  href={citation.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs flex items-center gap-1
                    text-accent hover:text-accent-light transition-colors"
                >
                  <ExternalLink size={12} />
                  View source
                </a>
              )}
            </div>
            {hasReturnAnchor && (
              <button
                onClick={onBackToText}
                className="text-xs flex items-center gap-1 px-2 py-0.5 rounded
                  dark:text-dark-300 dark:hover:text-warm-200
                  light:text-warm-500 light:hover:text-warm-600
                  transition-colors ml-auto"
              >
                <ArrowUp size={12} />
                Back to text
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
