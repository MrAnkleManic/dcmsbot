import { useState, useCallback } from 'react';
import { useTheme } from './hooks/useTheme';
import { queryBot } from './lib/api';
import Header from './components/Header';
import SearchInput from './components/SearchInput';
import EmptyState from './components/EmptyState';
import LoadingSkeleton from './components/LoadingSkeleton';
import AnswerPanel from './components/AnswerPanel';
import SourcesList from './components/SourcesList';
import RefusalMessage from './components/RefusalMessage';
import ErrorMessage from './components/ErrorMessage';
import SettingsDrawer from './components/SettingsDrawer';
import KbStatsPanel from './components/KbStatsPanel';
import KbHealthPanel from './components/KbHealthPanel';
import ShareButtons from './components/ShareButtons';

const MAX_CONVERSATION_TURNS = 6; // 3 exchanges (user + assistant pairs)

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [scrollToFilters, setScrollToFilters] = useState(false);
  const [kbHealthOpen, setKbHealthOpen] = useState(false);

  const [filters, setFilters] = useState({
    primary_only: false,
    include_guidance: true,
    include_debates: true,
    enabled_categories: null, // null = all categories enabled (default)
  });

  const [debug, setDebug] = useState({
    include_kb_status: false,
    include_retrieval_debug: false,
    include_evidence_pack: false,
  });

  // Query state
  const [status, setStatus] = useState('idle'); // idle | loading | success | refused | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [lastQuery, setLastQuery] = useState('');

  // Conversation history for multi-turn support
  const [conversationHistory, setConversationHistory] = useState([]);

  const handleSubmit = async (question) => {
    setStatus('loading');
    setError(null);
    setLastQuery(question);

    try {
      const data = await queryBot({
        question,
        filters,
        debug,
        conversation_history: conversationHistory.length > 0 ? conversationHistory : undefined,
      });

      if (data.answer?.refused || data.status === 'insufficient_evidence' || data.status === 'refused') {
        setResult(data);
        setStatus('refused');
      } else {
        setResult(data);
        setStatus('success');
      }

      // Append this turn pair to conversation history
      const answerText = data.answer?.text || '';
      if (answerText) {
        setConversationHistory(prev => {
          const updated = [
            ...prev,
            { role: 'user', content: question },
            { role: 'assistant', content: answerText },
          ];
          // Keep only the most recent turns
          return updated.slice(-MAX_CONVERSATION_TURNS);
        });
      }
    } catch (err) {
      setError(err.message);
      setStatus('error');
    }
  };

  const handleExampleClick = (question) => {
    handleSubmit(question);
  };

  const handleRetry = () => {
    if (lastQuery) handleSubmit(lastQuery);
  };

  const handleNewConversation = useCallback(() => {
    setConversationHistory([]);
    setStatus('idle');
    setResult(null);
    setError(null);
    setLastQuery('');
  }, []);

  const handleOpenFilters = useCallback(() => {
    setScrollToFilters(true);
    setSettingsOpen(true);
  }, []);

  const handleCloseSettings = useCallback(() => {
    setSettingsOpen(false);
    setScrollToFilters(false);
  }, []);

  // The question to display: use rewritten if available, otherwise the original
  const displayQuestion = result?.rewritten_question || lastQuery;
  const wasRewritten = result?.rewritten_question && result.rewritten_question !== lastQuery;

  return (
    <div className="min-h-screen dark:bg-dark-800 light:bg-warm-50 transition-colors">
      <Header
        theme={theme}
        toggleTheme={toggleTheme}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenKbHealth={() => setKbHealthOpen(true)}
      />

      {kbHealthOpen && (
        <KbHealthPanel onClose={() => setKbHealthOpen(false)} />
      )}

      <div className="flex">
        {/* Left sidebar - KB Stats */}
        <aside className="hidden lg:block w-64 shrink-0 p-4 pt-6 sticky top-0 h-screen overflow-y-auto
          border-r dark:border-dark-600 light:border-warm-200">
          <KbStatsPanel onOpenFilters={handleOpenFilters} />
        </aside>

        {/* Main content */}
        <main className="flex-1 max-w-3xl mx-auto px-6 pb-8">
          {/* Sticky search bar */}
          <div className="sticky top-0 z-10 pt-4 pb-3
            dark:bg-dark-800 light:bg-warm-50">
            <SearchInput
              onSubmit={handleSubmit}
              isLoading={status === 'loading'}
              hasHistory={conversationHistory.length > 0}
              onNewConversation={handleNewConversation}
            />
          </div>

          {status === 'idle' && (
            <EmptyState onSelectExample={handleExampleClick} />
          )}

          {status === 'loading' && <LoadingSkeleton />}

          {status === 'error' && (
            <ErrorMessage message={error} onRetry={handleRetry} />
          )}

          {status === 'refused' && result && (
            <>
              {/* Show the question */}
              {lastQuery && (
                <div className="mb-4">
                  <p className="text-base font-medium dark:text-warm-100 light:text-dark-800">
                    {lastQuery}
                  </p>
                  {wasRewritten && (
                    <p className="text-sm mt-1 italic
                      dark:text-dark-300 light:text-warm-500">
                      Interpreted as: &ldquo;{result.rewritten_question}&rdquo;
                    </p>
                  )}
                </div>
              )}
              <RefusalMessage data={result} />
              <ShareButtons
                question={lastQuery}
                answerText={result.message_user || result.answer?.refusal_reason || 'Unable to find sufficient evidence to answer this question.'}
                citations={result.closest_matches?.map((m, i) => ({
                  citation_id: `match-${i + 1}`,
                  title: m.title,
                  source_type: m.source_type || 'Unknown',
                }))}
              />
            </>
          )}

          {status === 'success' && result && (
            <>
              {/* Show the question being answered */}
              {lastQuery && (
                <div className="mb-4">
                  <p className="text-base font-medium dark:text-warm-100 light:text-dark-800">
                    {lastQuery}
                  </p>
                  {wasRewritten && (
                    <p className="text-sm mt-1 italic
                      dark:text-dark-300 light:text-warm-500">
                      Interpreted as: &ldquo;{result.rewritten_question}&rdquo;
                    </p>
                  )}
                </div>
              )}
              <AnswerPanel data={result} />
              <ShareButtons
                question={lastQuery}
                answerText={result.answer?.text}
                citations={result.citations}
              />
              <SourcesList citations={result.citations} />

              {debug.include_retrieval_debug && result.retrieval_debug && (
                <div className="mt-8">
                  <h3 className="text-xs font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-3">
                    Retrieval Debug
                  </h3>
                  <div className="overflow-x-auto rounded-lg border dark:border-dark-500 light:border-warm-300">
                    <table className="w-full text-xs">
                      <thead className="dark:bg-dark-600 light:bg-warm-100">
                        <tr>
                          <th className="px-3 py-2 text-left dark:text-dark-300 light:text-warm-400">Rank</th>
                          <th className="px-3 py-2 text-left dark:text-dark-300 light:text-warm-400">Title</th>
                          <th className="px-3 py-2 text-left dark:text-dark-300 light:text-warm-400">Type</th>
                          <th className="px-3 py-2 text-right dark:text-dark-300 light:text-warm-400">Score</th>
                          <th className="px-3 py-2 text-left dark:text-dark-300 light:text-warm-400">Flags</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y dark:divide-dark-600 light:divide-warm-200">
                        {result.retrieval_debug.results?.map((r) => (
                          <tr key={r.rank} className="dark:text-warm-300 light:text-dark-600">
                            <td className="px-3 py-1.5 font-mono">{r.rank}</td>
                            <td className="px-3 py-1.5 truncate max-w-[200px]">{r.title}</td>
                            <td className="px-3 py-1.5">{r.doc_type}</td>
                            <td className="px-3 py-1.5 text-right font-mono">{r.relevance_score?.toFixed(3)}</td>
                            <td className="px-3 py-1.5 font-mono text-dark-400">{r.reason_flags?.join(', ')}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {debug.include_kb_status && result.kb_status && (
                <div className="mt-6">
                  <h3 className="text-xs font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-3">
                    KB Status
                  </h3>
                  <pre className="text-xs dark:bg-dark-700 light:bg-warm-100 dark:text-warm-300 light:text-dark-600 p-4 rounded-lg overflow-x-auto border dark:border-dark-500 light:border-warm-300">
                    {JSON.stringify(result.kb_status, null, 2)}
                  </pre>
                </div>
              )}
            </>
          )}
        </main>
      </div>

      <SettingsDrawer
        isOpen={settingsOpen}
        onClose={handleCloseSettings}
        theme={theme}
        toggleTheme={toggleTheme}
        filters={filters}
        onFiltersChange={setFilters}
        debug={debug}
        onDebugChange={setDebug}
        scrollToFilters={scrollToFilters}
      />
    </div>
  );
}
