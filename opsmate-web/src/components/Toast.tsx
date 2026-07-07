import React, { useState, useEffect, useCallback } from 'react';
import { X, AlertCircle, CheckCircle, AlertTriangle, Info } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export interface ToastMessage {
  id: string;
  type: ToastType;
  title: string;
  message: string;
  duration?: number;
}

interface ToastItemProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

const ICONS: Record<ToastType, React.ReactNode> = {
  success: <CheckCircle size={16} className="text-green-500 shrink-0" />,
  error: <AlertCircle size={16} className="text-red-500 shrink-0" />,
  warning: <AlertTriangle size={16} className="text-amber-500 shrink-0" />,
  info: <Info size={16} className="text-blue-500 shrink-0" />,
};

const BORDERS: Record<ToastType, string> = {
  success: 'border-l-4 border-l-green-500',
  error: 'border-l-4 border-l-red-500',
  warning: 'border-l-4 border-l-amber-500',
  info: 'border-l-4 border-l-blue-500',
};

function ToastItem({ toast, onDismiss }: ToastItemProps): JSX.Element {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const duration = toast.duration ?? 5000;
    const timer = setTimeout(() => {
      setIsExiting(true);
      setTimeout(() => onDismiss(toast.id), 300);
    }, duration);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration, onDismiss]);

  const handleDismiss = () => {
    setIsExiting(true);
    setTimeout(() => onDismiss(toast.id), 300);
  };

  return (
    <div
      className={`toast ${BORDERS[toast.type]} bg-white border border-opsmate-200 shadow-elevated rounded-lg ${
        isExiting ? 'opacity-0 translate-x-4' : 'opacity-100 translate-x-0'
      } transition-all duration-300`}
    >
      {ICONS[toast.type]}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-opsmate-800">{toast.title}</p>
        {toast.message && (
          <p className="text-xs text-opsmate-500 mt-0.5 leading-relaxed">{toast.message}</p>
        )}
      </div>
      <button
        onClick={handleDismiss}
        className="p-1 rounded-md hover:bg-opsmate-100 text-opsmate-400 hover:text-opsmate-600 shrink-0"
      >
        <X size={14} />
      </button>
    </div>
  );
}

let toastIdCounter = 0;

function generateToastId(): string {
  toastIdCounter += 1;
  return `toast-${Date.now()}-${toastIdCounter}`;
}

export function ToastContainer(): JSX.Element {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const addToast = useCallback((toast: Omit<ToastMessage, 'id'>) => {
    const id = generateToastId();
    setToasts((prev) => [...prev, { ...toast, id }]);
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  // Listen for global toast events from the API client
  useEffect(() => {
    const handleToastEvent = (event: Event) => {
      const customEvent = event as CustomEvent<{ type: ToastType; title: string; message: string }>;
      if (customEvent.detail) {
        const { type, title, message } = customEvent.detail;
        addToast({ type, title, message });
      }
    };

    window.addEventListener('opsmate-toast', handleToastEvent);
    return () => window.removeEventListener('opsmate-toast', handleToastEvent);
  }, [addToast]);

  // Also listen for success toast events
  useEffect(() => {
    const handleSuccessEvent = (event: Event) => {
      const customEvent = event as CustomEvent<{ title: string; message: string }>;
      if (customEvent.detail) {
        const { title, message } = customEvent.detail;
        addToast({ type: 'success', title, message });
      }
    };

    window.addEventListener('opsmate-success', handleSuccessEvent);
    return () => window.removeEventListener('opsmate-success', handleSuccessEvent);
  }, [addToast]);

  if (toasts.length === 0) {
    return <></>;
  }

  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <ToastItem key={toast.id} toast={toast} onDismiss={dismissToast} />
      ))}
    </div>
  );
}

export function useToast() {
  const showToast = useCallback((type: ToastType, title: string, message?: string) => {
    window.dispatchEvent(
      new CustomEvent('opsmate-toast', {
        detail: { type, title, message: message ?? '' },
      })
    );
  }, []);

  const showSuccess = useCallback(
    (title: string, message?: string) => showToast('success', title, message),
    [showToast]
  );
  const showError = useCallback(
    (title: string, message?: string) => showToast('error', title, message),
    [showToast]
  );
  const showWarning = useCallback(
    (title: string, message?: string) => showToast('warning', title, message),
    [showToast]
  );
  const showInfo = useCallback(
    (title: string, message?: string) => showToast('info', title, message),
    [showToast]
  );

  return { showToast, showSuccess, showError, showWarning, showInfo };
}

export default ToastContainer;
