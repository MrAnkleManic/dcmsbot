import { Info, Lightbulb } from 'lucide-react';
import SourceCard from './SourceCard';

export default function RefusalMessage({ data }) {
  const message = data.message_user || data.answer?.refusal_reason || 'Unable to find sufficient evidence to answer this question.';
  const suggestions = data.suggestions;
  const closestMatches = data.closest_matches;

  // Check if the LLM provided a rich refusal (contains newlines or bullet points)
  const isRichRefusal = message.includes('\n') || message.includes('- ') || message.includes('* ');

  return (
    <div className="space-y-6">
      <div className="rounded-lg border px-5 py-4 dark:bg-amber-950/20 dark:border-amber-900/30 light:bg-amber-50 light:border-amber-200">
        <div className="flex items-start gap-3">
          <Info size={18} className="dark:text-amber-400 light:text-amber-600 mt-0.5 shrink-0" />
          <div className="min-w-0">
            {isRichRefusal ? (
              <div className="text-sm dark:text-amber-200 light:text-amber-800 space-y-2">
                {message.split('\n').map((line, i) => {
                  const trimmed = line.trim();
                  if (!trimmed) return null;
                  if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
                    return (
                      <p key={i} className="pl-3 text-xs dark:text-amber-300/80 light:text-amber-700">
                        &bull; {trimmed.slice(2)}
                      </p>
                    );
                  }
                  return <p key={i}>{trimmed}</p>;
                })}
              </div>
            ) : (
              <p className="text-sm dark:text-amber-200 light:text-amber-800">{message}</p>
            )}
          </div>
        </div>
      </div>

      {suggestions && suggestions.length > 0 && (
        <div className="rounded-lg border px-5 py-4 dark:bg-dark-700/50 dark:border-dark-500 light:bg-warm-50 light:border-warm-200">
          <div className="flex items-start gap-3">
            <Lightbulb size={16} className="dark:text-accent light:text-accent mt-0.5 shrink-0" />
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-2">
                Suggestions
              </p>
              <ul className="space-y-1.5">
                {suggestions.map((s, i) => (
                  <li key={i} className="text-sm dark:text-warm-300 light:text-dark-600">
                    &bull; {s}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {closestMatches && closestMatches.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wider dark:text-dark-300 light:text-warm-400 mb-3">
            Closest matches
          </h3>
          <div className="space-y-2">
            {closestMatches.map((match, i) => (
              <SourceCard
                key={match.chunk_id || i}
                citation={{
                  citation_id: `match-${i}`,
                  title: match.title,
                  source_type: match.source_type || 'Unknown',
                  location_pointer: match.location_pointer || match.header,
                  date_published: match.date_published,
                  excerpt: match.chunk_text,
                  publisher: match.publisher,
                }}
                index={i}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
