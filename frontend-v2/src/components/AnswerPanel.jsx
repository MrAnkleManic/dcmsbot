import { useState, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import ConfidenceBadge from './ConfidenceBadge';
import { parseCitations, toSuperscript } from '../lib/citations';

// Unique counter for citation anchors so "back to text" can find them
let citationAnchorCounter = 0;

function CitationLink({ id, citations }) {
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipRef = useRef(null);
  const anchorRef = useRef(null);
  const [anchorId] = useState(() => `cite-ref-${++citationAnchorCounter}`);

  // Build the citation_id in C001 format to match SourceCard's DOM id
  const citationId = `C${String(id).padStart(3, '0')}`;

  // Find the matching citation for tooltip info
  const citation = citations?.find(c => c.citation_id === citationId);

  const handleClick = () => {
    // Dispatch custom event to expand sources panel first, include return anchor
    window.dispatchEvent(new CustomEvent('expand-sources', {
      detail: { citationId, returnAnchorId: anchorId }
    }));

    // Small delay to let the sources panel expand and render cards
    setTimeout(() => {
      const el = document.getElementById(`source-${citationId}`);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        el.classList.add('ring-2', 'ring-accent');
        setTimeout(() => el.classList.remove('ring-2', 'ring-accent'), 2000);
      }
    }, 100);
  };

  return (
    <span
      id={anchorId}
      ref={anchorRef}
      className="relative inline-block"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button
        onClick={handleClick}
        className="text-accent hover:text-accent-light cursor-pointer text-xs align-super font-medium transition-colors"
      >
        {toSuperscript(Number(id))}
      </button>

      {showTooltip && citation && (
        <div
          ref={tooltipRef}
          className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2
            px-3 py-2.5 rounded-lg shadow-lg text-sm
            dark:bg-dark-600 dark:text-warm-200 dark:border dark:border-dark-400
            light:bg-white light:text-dark-700 light:border light:border-warm-300 light:shadow-md
            pointer-events-none min-w-[200px] max-w-[340px]"
        >
          <div className="font-semibold truncate">{citation.title}</div>
          <div className="flex items-center gap-2 mt-1 text-xs dark:text-dark-300 light:text-warm-500">
            <span>{citation.source_type}</span>
            {citation.location_pointer && (
              <>
                <span className="opacity-40">·</span>
                <span className="truncate">{citation.location_pointer}</span>
              </>
            )}
          </div>
          <div className="text-xs mt-1.5 dark:text-accent light:text-accent opacity-70">
            Click to view source
          </div>
          {/* Tooltip arrow */}
          <div className="absolute top-full left-1/2 -translate-x-1/2
            border-4 border-transparent
            dark:border-t-dark-600 light:border-t-white" />
        </div>
      )}
    </span>
  );
}

/** Custom renderer that intercepts text nodes to inject citation superscripts */
function TextWithCitations({ children, citations }) {
  if (typeof children !== 'string') return children;
  const parts = parseCitations(children);
  if (parts.length <= 1 && parts[0]?.type === 'text') return children;

  return (
    <>
      {parts.map((part, i) =>
        part.type === 'citation' ? (
          <CitationLink key={i} id={part.id} citations={citations} />
        ) : (
          <span key={i}>{part.value}</span>
        )
      )}
    </>
  );
}

function makeMarkdownComponents(citations) {
  return {
    p: ({ children }) => (
      <p className="mb-3 leading-relaxed">
        {Array.isArray(children)
          ? children.map((child, i) => <TextWithCitations key={i} citations={citations}>{child}</TextWithCitations>)
          : <TextWithCitations citations={citations}>{children}</TextWithCitations>}
      </p>
    ),
    li: ({ children }) => (
      <li className="leading-relaxed">
        {Array.isArray(children)
          ? children.map((child, i) => <TextWithCitations key={i} citations={citations}>{child}</TextWithCitations>)
          : <TextWithCitations citations={citations}>{children}</TextWithCitations>}
      </li>
    ),
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  };
}

export default function AnswerPanel({ data }) {
  const { answer, citations } = data;
  const components = makeMarkdownComponents(citations);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <ConfidenceBadge level={answer.confidence?.level || 'medium'} />
        {answer.section_lock && answer.section_lock !== 'off' && (
          <span className="text-xs dark:text-dark-300 light:text-warm-400 dark:bg-dark-600 light:bg-warm-100 px-2 py-0.5 rounded">
            Locked to {answer.section_lock}
          </span>
        )}
      </div>

      <div className="prose dark:text-warm-200 light:text-dark-800 max-w-none">
        <ReactMarkdown components={components}>
          {answer.text}
        </ReactMarkdown>
      </div>
    </div>
  );
}
