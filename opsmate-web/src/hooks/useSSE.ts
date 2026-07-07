import { useState, useEffect, useRef, useCallback } from 'react';
import type { SSEEvent } from '@/types/api';
import { SSEEventTypeSchema } from '@/types/api';

export interface UseSSEOptions {
  /** SSE stream URL */
  url: string | null;
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Reconnect delay in ms (default: 3000) */
  reconnectDelay?: number;
  /** Max reconnect attempts (default: 10) */
  maxReconnects?: number;
}

export interface UseSSEReturn {
  /** All received events */
  events: SSEEvent[];
  /** Whether currently connected */
  isConnected: boolean;
  /** Error if connection failed */
  error: string | null;
  /** Number of reconnection attempts made */
  reconnectAttempts: number;
  /** Manually disconnect */
  disconnect: () => void;
  /** Manually reconnect */
  reconnect: () => void;
}

/**
 * Custom hook for managing Server-Sent Events (SSE) connections.
 * Handles connection lifecycle, event parsing, auto-reconnect, and cleanup.
 */
export function useSSE(options: UseSSEOptions): UseSSEReturn {
  const {
    url,
    autoReconnect = true,
    reconnectDelay = 3000,
    maxReconnects = 10,
  } = options;

  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reconnectAttempts, setReconnectAttempts] = useState(0);

  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isManualDisconnect = useRef(false);

  const clearReconnectTimeout = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  const closeConnection = useCallback(() => {
    clearReconnectTimeout();
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, [clearReconnectTimeout]);

  const connect = useCallback(() => {
    // Don't connect if no URL
    if (!url) return;

    // Close any existing connection
    closeConnection();

    isManualDisconnect.current = false;
    setError(null);

    try {
      const es = new EventSource(url);
      eventSourceRef.current = es;

      es.onopen = () => {
        setIsConnected(true);
        setError(null);
        setReconnectAttempts(0);
      };

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          // The event type comes from the `event:` field in SSE, which maps to `event.type`
          // EventSource doesn't expose event type in onmessage, so we handle typed events below
          // For generic messages without a type field, skip
          if (data && typeof data === 'object' && !data.type) {
            // Try to infer from common fields
            if (data.execution_id && data.summary) {
              setEvents((prev) => [
                ...prev,
                { type: 'execution.completed', payload: data },
              ]);
            }
          }
        } catch {
          // Non-JSON message, ignore
        }
      };

      // Handle typed events
      const eventTypes = SSEEventTypeSchema.options.map((o) => o.value);
      eventTypes.forEach((eventType) => {
        es.addEventListener(eventType, (event: MessageEvent) => {
          try {
            const payload = JSON.parse(event.data);
            const sseEvent: SSEEvent = { type: eventType, payload } as SSEEvent;
            setEvents((prev) => [...prev, sseEvent]);
          } catch (err) {
            console.warn(`Failed to parse SSE event "${eventType}":`, err);
          }
        });
      });

      es.onerror = () => {
        setIsConnected(false);

        if (isManualDisconnect.current) {
          closeConnection();
          return;
        }

        if (autoReconnect && reconnectAttempts < maxReconnects) {
          setReconnectAttempts((prev) => prev + 1);
          reconnectTimeoutRef.current = setTimeout(() => {
            connect();
          }, reconnectDelay);
        } else if (reconnectAttempts >= maxReconnects) {
          setError(`Max reconnection attempts (${maxReconnects}) reached.`);
          closeConnection();
        }
      };
    } catch (err) {
      setError(`Failed to create SSE connection: ${String(err)}`);
      setIsConnected(false);
    }
  }, [url, autoReconnect, reconnectDelay, maxReconnects, reconnectAttempts, closeConnection]);

  const disconnect = useCallback(() => {
    isManualDisconnect.current = true;
    setIsConnected(false);
    closeConnection();
  }, [closeConnection]);

  const reconnect = useCallback(() => {
    setReconnectAttempts(0);
    connect();
  }, [connect]);

  // Auto-connect when URL changes
  useEffect(() => {
    if (url) {
      connect();
    }
    return () => {
      isManualDisconnect.current = true;
      closeConnection();
    };
  }, [url]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isManualDisconnect.current = true;
      closeConnection();
    };
  }, [closeConnection]);

  return {
    events,
    isConnected,
    error,
    reconnectAttempts,
    disconnect,
    reconnect,
  };
}

export default useSSE;
