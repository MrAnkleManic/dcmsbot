import { useState, useEffect } from 'react';
import { Search, FileText, Landmark, MessageSquare, Sparkles } from 'lucide-react';

const stages = [
  { icon: Search, text: 'Searching knowledge base...', delay: 0 },
  { icon: FileText, text: 'Retrieving evidence chunks...', delay: 1500 },
  { icon: Landmark, text: 'Checking Parliament Written Answers...', delay: 3500 },
  { icon: MessageSquare, text: 'Searching Hansard debates...', delay: 6000 },
  { icon: Sparkles, text: 'Synthesising answer...', delay: 9000 },
];

export default function LoadingSkeleton() {
  const [activeStage, setActiveStage] = useState(0);

  useEffect(() => {
    const timers = stages.map((stage, i) =>
      setTimeout(() => setActiveStage(i), stage.delay)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="py-6 space-y-3">
      {stages.map((stage, i) => {
        const Icon = stage.icon;
        const isActive = i === activeStage;
        const isDone = i < activeStage;
        const isPending = i > activeStage;

        return (
          <div
            key={i}
            className={`flex items-center gap-3 transition-all duration-500
              ${isPending ? 'opacity-0 translate-y-2' : 'opacity-100 translate-y-0'}
              ${isDone ? 'opacity-40' : ''}`}
          >
            <div className={`shrink-0 transition-colors duration-300
              ${isActive ? 'text-accent' : 'dark:text-dark-400 light:text-warm-400'}`}>
              <Icon size={16} className={isActive ? 'animate-pulse' : ''} />
            </div>
            <span className={`text-sm transition-colors duration-300
              ${isActive
                ? 'dark:text-warm-200 light:text-dark-700 font-medium'
                : 'dark:text-dark-400 light:text-warm-400'}`}>
              {stage.text}
            </span>
            {isDone && (
              <span className="text-xs dark:text-dark-500 light:text-warm-300 ml-auto">
                done
              </span>
            )}
          </div>
        );
      })}

      {/* Skeleton lines below the stages */}
      <div className="pt-4 space-y-3 animate-pulse">
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-full" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-11/12" />
        <div className="h-4 rounded dark:bg-dark-600 light:bg-warm-200 w-4/5" />
      </div>
    </div>
  );
}
