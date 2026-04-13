import { Scale } from 'lucide-react';

const examples = [
  'What patterns are emerging in how Ofcom prioritises its enforcement investigations?',
  'How does Ofcom\'s approach to age assurance compare with what Parliament intended?',
  'What should a compliance team at a mid-sized platform be doing right now?',
  'What impact did the Select Committee\'s scrutiny have on the final shape of the Act?',
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
