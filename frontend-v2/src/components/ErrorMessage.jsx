import { AlertCircle } from 'lucide-react';

export default function ErrorMessage({ message, onRetry }) {
  return (
    <div className="rounded-lg border px-5 py-4 dark:bg-red-950/20 dark:border-red-900/30 light:bg-red-50 light:border-red-200">
      <div className="flex items-start gap-3">
        <AlertCircle size={18} className="dark:text-red-400 light:text-red-500 mt-0.5 shrink-0" />
        <div className="flex-1">
          <p className="text-sm dark:text-red-300 light:text-red-700">
            {message || 'Something went wrong. Please check if the backend is running.'}
          </p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="text-xs mt-2 dark:text-red-400 dark:hover:text-red-300 light:text-red-600 light:hover:text-red-500 underline"
            >
              Try again
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
