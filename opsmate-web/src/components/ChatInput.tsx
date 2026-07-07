import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Send, ChevronDown, Wand2, Server, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/context/AuthContext';
import type { ExecutionMode } from '@/types/api';

export interface ChatInputProps {
  onSubmit: (text: string, options: {
    autoApprove: boolean;
    modeOverride: ExecutionMode | null;
  }) => void;
  isLoading: boolean;
  disabled?: boolean;
  exampleCommands?: Array<{ title: string; description: string; command: string }>;
}

export function ChatInput({
  onSubmit,
  isLoading,
  disabled = false,
  exampleCommands = [],
}: ChatInputProps): JSX.Element {
  const [text, setText] = useState('');
  const [autoApprove, setAutoApprove] = useState(false);
  const [modeOverride, setModeOverride] = useState<ExecutionMode | null>(null);
  const [showExamples, setShowExamples] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { isAuthenticated } = useAuth();

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    const maxHeight = 200;
    textarea.style.height = `${Math.min(textarea.scrollHeight, maxHeight)}px`;
  }, [text]);

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed || isLoading || disabled) return;

    onSubmit(trimmed, {
      autoApprove,
      modeOverride,
    });
    setText('');
    setShowExamples(false);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [text, isLoading, disabled, autoApprove, modeOverride, onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit]
  );

  const handleExampleClick = useCallback(
    (command: string) => {
      setText(command);
      setShowExamples(false);
      textareaRef.current?.focus();
    },
    []
  );

  const isSubmitDisabled = !text.trim() || isLoading || disabled || !isAuthenticated;

  return (
    <div className="border-t border-opsmate-200 bg-white px-4 py-3">
      {/* Example commands dropdown */}
      {exampleCommands.length > 0 && (
        <div className="mb-2">
          <button
            onClick={() => setShowExamples((prev) => !prev)}
            className="flex items-center gap-1.5 text-xs font-medium text-opsmate-500 hover:text-opsmate-700 transition-colors"
          >
            <Wand2 size={12} />
            <span>Example Commands</span>
            <ChevronDown
              size={12}
              className={`transition-transform ${showExamples ? 'rotate-180' : ''}`}
            />
          </button>

          {showExamples && (
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2 animate-enter">
              {exampleCommands.map((example, index) => (
                <button
                  key={index}
                  onClick={() => handleExampleClick(example.command)}
                  className="text-left p-2.5 rounded-lg bg-opsmate-50 border border-opsmate-100 hover:border-opsmate-300 hover:bg-opsmate-100 transition-all group"
                >
                  <p className="text-xs font-semibold text-opsmate-700 group-hover:text-opsmate-900">
                    {example.title}
                  </p>
                  <p className="text-2xs text-opsmate-400 mt-0.5 line-clamp-1">
                    {example.description}
                  </p>
                  <p className="text-2xs font-mono text-opsmate-500 mt-1 truncate">
                    {example.command}
                  </p>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Options bar */}
      <div className="flex items-center gap-3 mb-2">
        <button
          onClick={() => setShowOptions((prev) => !prev)}
          className="flex items-center gap-1 text-2xs font-medium text-opsmate-400 hover:text-opsmate-600 transition-colors"
        >
          <ShieldCheck size={12} />
          <span>Options</span>
          <ChevronDown
            size={10}
            className={`transition-transform ${showOptions ? 'rotate-180' : ''}`}
          />
        </button>

        {showOptions && (
          <div className="flex items-center gap-4 animate-enter">
            {/* Auto-approve toggle */}
            <label className="flex items-center gap-1.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={autoApprove}
                onChange={(e) => setAutoApprove(e.target.checked)}
                className="w-3.5 h-3.5 rounded border-opsmate-300 text-opsmate-700 focus:ring-opsmate-500"
              />
              <span className="text-2xs font-medium text-opsmate-500">Auto-approve</span>
            </label>

            {/* Mode override */}
            <div className="flex items-center gap-1.5">
              <Server size={12} className="text-opsmate-400" />
              <select
                value={modeOverride ?? ''}
                onChange={(e) =>
                  setModeOverride((e.target.value as ExecutionMode) || null)
                }
                className="text-2xs bg-opsmate-50 border border-opsmate-200 rounded px-1.5 py-0.5 text-opsmate-600 focus:outline-none focus:ring-1 focus:ring-opsmate-400"
              >
                <option value="">Default Mode</option>
                <option value="mock">Mock</option>
                <option value="live">Live</option>
                <option value="mixed">Mixed</option>
              </select>
            </div>
          </div>
        )}
      </div>

      {/* Input area */}
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isAuthenticated
                ? 'Type a command... (Ctrl+Enter to send)'
                : 'Enter your API key to start...'
            }
            disabled={disabled || !isAuthenticated}
            rows={1}
            className="w-full resize-none rounded-xl border border-opsmate-200 bg-opsmate-50 px-4 py-3 text-sm text-opsmate-900 placeholder:text-opsmate-400 focus:outline-none focus:ring-2 focus:ring-opsmate-400 focus:border-transparent disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={isSubmitDisabled}
          className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center transition-all ${
            isSubmitDisabled
              ? 'bg-opsmate-200 text-opsmate-400 cursor-not-allowed'
              : 'bg-opsmate-800 text-white hover:bg-opsmate-700 shadow-soft active:scale-95'
          }`}
        >
          <Send size={16} />
        </button>
      </div>
    </div>
  );
}

export default ChatInput;
