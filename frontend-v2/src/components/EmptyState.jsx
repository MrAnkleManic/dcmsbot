import { Scale } from 'lucide-react';

const examples = [
  'What are the duties on Category 1 services?',
  'What does Section 44 say about Ofcom\'s powers?',
  'How does the Act define illegal content?',
  'What are the transparency reporting requirements?',
];

export default function EmptyState({ onSelectExample }) {
  return (
    <div className="text-center py-16">
      <Scale size={40} className="mx-auto dark:text-dark-400 light:text-warm-300 mb-4" />
      <p className="dark:text-dark-300 light:text-warm-400 text-sm mb-8">
        Ask a question to search the evidence base
      </p>
      <div className="space-y-2 max-w-md mx-auto">
        <p className="text-xs uppercase tracking-wider dark:text-dark-400 light:text-warm-400 mb-3">
          Try asking
        </p>
        {examples.map((q) => (
          <button
            key={q}
            onClick={() => onSelectExample(q)}
            className="block w-full text-left text-sm px-4 py-2.5 rounded-lg transition-colors
              dark:text-warm-300 dark:hover:bg-dark-600 dark:hover:text-warm-100
              light:text-dark-700 light:hover:bg-warm-100 light:hover:text-dark-800"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
