'use client';

import React, { useEffect } from 'react';

export type ToastVariant = 'error' | 'success' | 'info' | 'warning';

export interface ToastMessage {
  id: number;
  variant: ToastVariant;
  message: string;
}

const variantClasses: Record<ToastVariant, string> = {
  error: 'border-red-200 bg-red-50 text-red-800',
  success: 'border-green-200 bg-green-50 text-green-800',
  info: 'border-blue-200 bg-blue-50 text-blue-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
};

interface ToastProps {
  toast: ToastMessage;
  onDismiss: (id: number) => void;
  duration?: number;
}

function Toast({ toast, onDismiss, duration = 5000 }: ToastProps) {
  useEffect(() => {
    const t = setTimeout(() => onDismiss(toast.id), duration);
    return () => clearTimeout(t);
  }, [toast.id, duration, onDismiss]);

  return (
    <div
      role="status"
      className={`flex items-start gap-3 rounded-md border px-4 py-3 text-sm shadow-md ${variantClasses[toast.variant]}`}
    >
      <span className="flex-1">{toast.message}</span>
      <button
        type="button"
        onClick={() => onDismiss(toast.id)}
        className="text-current opacity-60 hover:opacity-100"
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  );
}

interface ToastContainerProps {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  if (toasts.length === 0) return null;
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-full max-w-sm flex-col gap-2">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

export default Toast;
