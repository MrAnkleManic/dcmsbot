const config = {
  high: { label: 'High confidence', dots: 3, color: 'bg-confidence-high' },
  medium: { label: 'Medium confidence', dots: 2, color: 'bg-confidence-medium' },
  low: { label: 'Low confidence', dots: 1, color: 'bg-confidence-low' },
};

export default function ConfidenceBadge({ level }) {
  const c = config[level] || config.medium;
  return (
    <div className="inline-flex items-center gap-1.5" title={c.label}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className={`w-1.5 h-1.5 rounded-full ${i < c.dots ? c.color : 'dark:bg-dark-500 light:bg-warm-300'}`}
        />
      ))}
      <span className="text-xs dark:text-dark-300 light:text-warm-400 ml-1">
        {c.label}
      </span>
    </div>
  );
}
