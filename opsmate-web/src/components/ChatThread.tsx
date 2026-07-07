import React, { useRef, useEffect } from 'react';
import { ChatMessage } from './ChatMessage';

export interface ThreadMessage {
  id: string;
  role: 'user' | 'system';
  content: string;
  metadata?: {
    planSteps?: number;
    executionTime?: number;
    mode?: string;
  };
}

export interface ChatThreadProps {
  messages: ThreadMessage[];
  isLoading?: boolean;
  loadingText?: string;
}

export function ChatThread({
  messages,
  isLoading = false,
  loadingText = 'Processing...',
}: ChatThreadProps): JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when messages change or loading state changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin"
    >
      {messages.length === 0 && (
        <div className="h-full flex flex-col items-center justify-center text-center py-12">
          <div className="w-16 h-16 rounded-2xl bg-opsmate-100 flex items-center justify-center mb-4">
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-opsmate-500"
            >
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <h2 className="text-lg font-semibold text-opsmate-700 mb-2">
            Welcome to OpsMate
          </h2>
          <p className="text-sm text-opsmate-500 max-w-sm leading-relaxed">
            Infrastructure automation powered by MCP. Type a natural language command
to inspect, diagnose, and remediate your infrastructure.
          </p>
          <div className="mt-6 flex flex-wrap gap-2 justify-center max-w-md">
            {[
              'Check pod health in namespace prod',
              'List ECS services in us-east-1',
              'Search GitHub issues for memory leak',
              'Query database for slow queries',
            ].map((cmd) => (
              <span
                key={cmd}
                className="text-2xs px-2.5 py-1.5 rounded-lg bg-opsmate-100 text-opsmate-600 font-mono border border-opsmate-200"
              >
                {cmd}
              </span>
            ))}
          </div>
        </div>
      )}

      {messages.map((msg) => (
        <ChatMessage
          key={msg.id}
          role={msg.role}
          content={msg.content}
          metadata={msg.metadata}
        />
      ))}

      {isLoading && (
        <div className="flex items-center gap-3 animate-enter">
          <div className="w-7 h-7 rounded-full bg-opsmate-200 flex items-center justify-center">
            <div className="w-3.5 h-3.5 border-2 border-opsmate-400 border-t-transparent rounded-full animate-spin" />
          </div>
          <div className="message-system py-2.5">
            <div className="flex items-center gap-2">
              <div className="w-1.5 h-1.5 rounded-full bg-opsmate-400 animate-pulse" />
              <div className="w-1.5 h-1.5 rounded-full bg-opsmate-400 animate-pulse" style={{ animationDelay: '0.2s' }} />
              <div className="w-1.5 h-1.5 rounded-full bg-opsmate-400 animate-pulse" style={{ animationDelay: '0.4s' }} />
              <span className="text-xs text-opsmate-400 ml-1">{loadingText}</span>
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}

export default ChatThread;
