import React, { useState, useCallback } from 'react';
import { Copy, Check, ChevronDown, ChevronUp, User, Bot } from 'lucide-react';

export interface ChatMessageProps {
  role: 'user' | 'system';
  content: string;
  metadata?: {
    planSteps?: number;
    executionTime?: number;
    mode?: string;
  };
}

/**
 * Simple Markdown renderer for chat messages.
 * Handles: bold, italic, code, code blocks, lists, links, headings.
 */
function renderMarkdown(text: string): React.ReactNode {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let inCodeBlock = false;
  let codeBlockContent = '';
  let codeBlockLang = '';

  lines.forEach((line, idx) => {
    // Code blocks
    if (line.startsWith('```')) {
      if (inCodeBlock) {
        // End code block
        elements.push(
          <CodeBlock key={`code-${idx}`} language={codeBlockLang} content={codeBlockContent.trim()} />
        );
        codeBlockContent = '';
        codeBlockLang = '';
        inCodeBlock = false;
      } else {
        // Start code block
        inCodeBlock = true;
        codeBlockLang = line.slice(3).trim();
      }
      return;
    }

    if (inCodeBlock) {
      codeBlockContent += line + '\n';
      return;
    }

    // Empty line
    if (line.trim() === '') {
      elements.push(<div key={`br-${idx}`} className="h-2" />);
      return;
    }

    // Headings
    if (line.startsWith('### ')) {
      elements.push(
        <h3 key={idx} className="text-sm font-semibold mt-3 mb-1 text-opsmate-800">
          {parseInline(line.slice(4))}
        </h3>
      );
      return;
    }
    if (line.startsWith('## ')) {
      elements.push(
        <h2 key={idx} className="text-base font-semibold mt-4 mb-2 text-opsmate-800">
          {parseInline(line.slice(3))}
        </h2>
      );
      return;
    }
    if (line.startsWith('# ')) {
      elements.push(
        <h1 key={idx} className="text-lg font-bold mt-4 mb-2 text-opsmate-900">
          {parseInline(line.slice(2))}
        </h1>
      );
      return;
    }

    // Horizontal rule
    if (line.match(/^---+$/)) {
      elements.push(<hr key={idx} className="my-3 border-opsmate-200" />);
      return;
    }

    // Bullet lists
    if (line.match(/^[-*]\s/)) {
      elements.push(
        <ul key={idx} className="list-disc list-inside my-1">
          <li className="text-sm leading-relaxed">{parseInline(line.replace(/^[-*]\s/, ''))}</li>
        </ul>
      );
      return;
    }

    // Numbered lists
    const numberedMatch = line.match(/^\d+\.\s(.+)$/);
    if (numberedMatch) {
      elements.push(
        <ol key={idx} className="list-decimal list-inside my-1">
          <li className="text-sm leading-relaxed">{parseInline(numberedMatch[1])}</li>
        </ol>
      );
      return;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      elements.push(
        <blockquote
          key={idx}
          className="border-l-2 border-opsmate-300 pl-3 italic text-opsmate-600 my-2 text-sm"
        >
          {parseInline(line.slice(2))}
        </blockquote>
      );
      return;
    }

    // Regular paragraph
    elements.push(
      <p key={idx} className="text-sm leading-relaxed mb-1">
        {parseInline(line)}
      </p>
    );
  });

  // Unclosed code block
  if (inCodeBlock && codeBlockContent) {
    elements.push(
      <CodeBlock key="code-final" language={codeBlockLang} content={codeBlockContent.trim()} />
    );
  }

  return <>{elements}</>;
}

/**
 * Parse inline formatting: bold, italic, inline code, links.
 */
function parseInline(text: string): React.ReactNode {
  const parts: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  const patterns = [
    // Inline code
    { regex: /`([^`]+)`/g, type: 'code' as const },
  ];

  // Simple approach: process bold and italic with split
  const processText = (input: string): React.ReactNode[] => {
    const nodes: React.ReactNode[] = [];
    // Split by bold (**text**)
    const boldParts = input.split(/(\*\*[^*]+\*\*)/g);

    boldParts.forEach((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        const content = part.slice(2, -2);
        // Process italic inside bold
        const italicParts = content.split(/(\*[^*]+\*)/g);
        const italicNodes: React.ReactNode[] = [];
        italicParts.forEach((ip, j) => {
          if (ip.startsWith('*') && ip.endsWith('*') && ip.length > 2) {
            italicNodes.push(
              <em key={`${i}-${j}`} className="italic">
                {processInlineCode(ip.slice(1, -1))}
              </em>
            );
          } else {
            italicNodes.push(<span key={`${i}-${j}`}>{processInlineCode(ip)}</span>);
          }
        });
        nodes.push(
          <strong key={`bold-${i}`} className="font-semibold">
            {italicNodes}
          </strong>
        );
      } else {
        // Process italic
        const italicParts = part.split(/(\*[^*]+\*)/g);
        italicParts.forEach((ip, j) => {
          if (ip.startsWith('*') && ip.endsWith('*') && ip.length > 2) {
            nodes.push(
              <em key={`${i}-${j}`} className="italic">
                {processInlineCode(ip.slice(1, -1))}
              </em>
            );
          } else {
            nodes.push(<span key={`${i}-${j}`}>{processInlineCode(ip)}</span>);
          }
        });
      }
    });

    return nodes;
  };

  const processInlineCode = (input: string): React.ReactNode => {
    const codeParts = input.split(/(`[^`]+`)/g);
    return codeParts.map((part, i) => {
      if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
        return (
          <code key={i} className="inline-code">
            {part.slice(1, -1)}
          </code>
        );
      }
      return <span key={i}>{part}</span>;
    });
  };

  // Process links [text](url)
  const linkRegex = /\[([^\]]+)\]\(([^)]+)\)/g;
  let match;
  let lastIndex = 0;
  const linkNodes: React.ReactNode[] = [];

  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      linkNodes.push(...processText(text.slice(lastIndex, match.index)));
    }
    linkNodes.push(
      <a
        key={`link-${match.index}`}
        href={match[2]}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 hover:underline"
      >
        {match[1]}
      </a>
    );
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    linkNodes.push(...processText(text.slice(lastIndex)));
  }

  return linkNodes.length > 0 ? <>{linkNodes}</> : <>{processText(text)}</>;
}

/**
 * Code block with copy button.
 */
function CodeBlock({ language, content }: { language: string; content: string }): JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
      const textarea = document.createElement('textarea');
      textarea.value = content;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [content]);

  return (
    <div className="code-block my-2 group">
      <div className="flex items-center justify-between mb-2 pb-2 border-b border-opsmate-700">
        <span className="text-2xs font-mono text-opsmate-400">{language || 'text'}</span>
        <button
          onClick={handleCopy}
          className="copy-button p-1 rounded hover:bg-opsmate-700 text-opsmate-400 hover:text-opsmate-200 transition-colors"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
        </button>
      </div>
      <pre className="text-xs leading-relaxed overflow-x-auto">
        <code>{content}</code>
      </pre>
    </div>
  );
}

export function ChatMessage({ role, content, metadata }: ChatMessageProps): JSX.Element {
  const isUser = role === 'user';
  const [isJsonExpanded, setIsJsonExpanded] = useState(false);

  // Try to detect JSON content and offer collapsible view
  const jsonMatch = content.match(/```json\n([\s\S]*?)\n```/);
  const hasJsonBlock = !!jsonMatch;

  // Extract non-JSON part and JSON part
  const textContent = hasJsonBlock
    ? content.replace(/```json\n[\s\S]*?\n```/, '').trim()
    : content;

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''} animate-enter`}>
      {/* Avatar */}
      <div
        className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center ${
          isUser ? 'bg-opsmate-700' : 'bg-opsmate-200'
        }`}
      >
        {isUser ? (
          <User size={14} className="text-opsmate-100" />
        ) : (
          <Bot size={14} className="text-opsmate-600" />
        )}
      </div>

      {/* Message bubble */}
      <div className={`max-w-[80%] ${isUser ? 'message-user' : 'message-system'}`}>
        {isUser ? (
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{content}</p>
        ) : (
          <div className="markdown-content">
            {textContent && renderMarkdown(textContent)}

            {hasJsonBlock && (
              <div className="mt-2">
                <button
                  onClick={() => setIsJsonExpanded((prev) => !prev)}
                  className="flex items-center gap-1 text-2xs font-medium text-opsmate-400 hover:text-opsmate-600 mb-1"
                >
                  {isJsonExpanded ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                  <span>{isJsonExpanded ? 'Hide' : 'Show'} JSON output</span>
                </button>
                {isJsonExpanded && (
                  <div className="animate-enter">
                    <CodeBlock language="json" content={jsonMatch[1]} />
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Metadata footer */}
        {metadata && !isUser && (
          <div className="flex items-center gap-3 mt-2 pt-2 border-t border-opsmate-200/50">
            {metadata.planSteps !== undefined && (
              <span className="text-2xs text-opsmate-400">
                {metadata.planSteps} steps
              </span>
            )}
            {metadata.executionTime !== undefined && (
              <span className="text-2xs text-opsmate-400">
                {(metadata.executionTime / 1000).toFixed(1)}s
              </span>
            )}
            {metadata.mode && (
              <span className="text-2xs font-medium px-1.5 py-0.5 rounded-full bg-opsmate-100 text-opsmate-500 uppercase">
                {metadata.mode}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default ChatMessage;
