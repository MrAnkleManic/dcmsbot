import { formatApiUsage } from '../lib/apiUsage';

export default function ApiUsageFooter({ apiUsage }) {
  const formatted = formatApiUsage(apiUsage);
  if (!formatted) return null;

  return (
    <div
      data-testid="api-usage-footer"
      className="mt-4 pt-3 flex flex-wrap items-center gap-x-2 gap-y-1
        text-xs border-t
        dark:text-dark-300 light:text-warm-500
        dark:border-dark-600 light:border-warm-200"
    >
      <span className="uppercase tracking-wider dark:text-dark-400 light:text-warm-400">
        API usage
      </span>
      <span className="font-mono">{formatted.inputTokens} in</span>
      <span className="opacity-40">·</span>
      <span className="font-mono">{formatted.outputTokens} out</span>
      <span className="opacity-40">·</span>
      <span className="font-mono">{formatted.costUsd}</span>
    </div>
  );
}
