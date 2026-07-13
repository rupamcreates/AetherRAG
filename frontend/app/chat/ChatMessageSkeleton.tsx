import React from 'react';
import { RefreshCw } from 'lucide-react';

interface ChatMessageSkeletonProps {
  currentStage: string;
}

export const ChatMessageSkeleton: React.FC<ChatMessageSkeletonProps> = ({ currentStage }) => {
  // Map stages to user-friendly messages
  const getStageText = (stage: string) => {
    switch (stage) {
      case 'initiating':
        return 'Initializing connection...';
      case 'QUERY_EXPANSION':
        return 'Analyzing question & expanding search queries...';
      case 'HYBRID_RETRIEVAL':
        return 'Executing pgvector & lexical database searches...';
      case 'RERANKING':
        return 'Reranking retrieved document contexts...';
      case 'GENERATION':
        return 'Formulating final response...';
      default:
        return 'Analyzing knowledge graphs & formulating response...';
    }
  };

  return (
    <div className="flex gap-3 mr-auto max-w-[85%] w-full">
      {/* AI Icon/Avatar */}
      <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-lg bg-gradient-to-tr from-indigo-600 to-cyan-500 text-white font-bold text-xs shadow-lg shadow-indigo-500/20">
        AI
      </div>

      {/* Main Skeleton Bubble */}
      <div className="rounded-2xl border border-zinc-800/80 bg-zinc-950 px-4 py-4 text-sm text-zinc-300 w-full shadow-2xl">
        {/* Shifting Pulsing Paragraph Lines */}
        <div className="space-y-3">
          <div className="h-4 bg-zinc-800/60 rounded w-3/4 animate-pulse" />
          <div className="h-4 bg-zinc-800/60 rounded w-5/6 animate-pulse" />
          <div className="h-4 bg-zinc-800/60 rounded w-2/3 animate-pulse" />
          <div className="h-4 bg-zinc-800/60 rounded w-4/5 animate-pulse" />
        </div>

        {/* Dynamic Execution Stage Tracker */}
        <div className="mt-4 pt-3 border-t border-zinc-800/60 flex items-center gap-2 text-xs font-semibold text-blue-400/80 tracking-wide select-none">
          <div className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500 shadow-[0_0_8px_#3b82f6]"></span>
          </div>
          <span className="flex items-center gap-1.5 animate-pulse">
            <RefreshCw className="h-3.5 w-3.5 animate-spin text-blue-400/80" />
            {getStageText(currentStage)}
          </span>
        </div>
      </div>
    </div>
  );
};
