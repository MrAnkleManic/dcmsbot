export default function LoadingSkeleton() {
  return (
    <div className="space-y-4 animate-pulse py-4">
      <div className="flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-dark-500 light:bg-warm-300" />
        <div className="w-1.5 h-1.5 rounded-full bg-dark-500 light:bg-warm-300" />
        <div className="w-1.5 h-1.5 rounded-full bg-dark-500 light:bg-warm-300" />
        <div className="h-3 w-24 rounded dark:bg-dark-600 light:bg-warm-200 ml-2" />
      </div>
      <div className="space-y-3">
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-full" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-11/12" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-4/5" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-full" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-3/4" />
      </div>
      <div className="pt-6 space-y-2">
        <div className="h-3 w-20 rounded dark:bg-dark-600 light:bg-warm-200" />
        <div className="h-16 rounded-lg dark:bg-dark-600 light:bg-warm-200" />
        <div className="h-16 rounded-lg dark:bg-dark-600 light:bg-warm-200" />
      </div>
    </div>
  );
}
