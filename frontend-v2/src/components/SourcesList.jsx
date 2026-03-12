import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import SourceCard from './SourceCard';

export default function SourcesList({ citations }) {
  const [expanded, setExpanded] = useState(false);
  // Track which citation was most recently clicked and where to return to
  const [returnAnchors, setReturnAnchors] = useState({}); // citationId -> returnAnchorId

  // Listen for citation click events that request source expansion
  useEffect(() => {
    const handleExpand = (e) => {
      setExpanded(true);
      const { citationId, returnAnchorId } = e.detail || {};
      if (citationId && returnAnchorId) {
        setReturnAnchors(prev => ({ ...prev, [citationId]: returnAnchorId }));
      }
    };

    window.addEventListener('expand-sources', handleExpand);
    return () => window.removeEventListener('expand-sources', handleExpand);
  }, []);

  const handleBackToText = useCallback((citationId) => {
    const anchorId = returnAnchors[citationId];
    if (anchorId) {
      const el = document.getElementById(anchorId);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-accent');
        setTimeout(() => el.classList.remove('ring-2', 'ring-accent'), 1500);
      }
    }
  }, [returnAnchors]);

  if (!citations || citations.length === 0) return null;

  return (
    <div className="mt-8">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 group w-full text-left"
      >
        <span className="dark:text-dark-400 light:text-warm-400 group-hover:dark:text-dark-300 group-hover:light:text-warm-500 transition-colors">
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </span>
        <h2 className="text-sm font-semibold uppercase tracking-wider
          dark:text-dark-300 light:text-warm-400
          group-hover:dark:text-dark-200 group-hover:light:text-warm-500
          transition-colors">
          Sources ({citations.length})
        </h2>
      </button>

      {expanded && (
        <div className="space-y-2 mt-3">
          {citations.map((c, i) => (
            <SourceCard
              key={c.citation_id || i}
              citation={c}
              index={i}
              hasReturnAnchor={!!returnAnchors[c.citation_id]}
              onBackToText={() => handleBackToText(c.citation_id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
