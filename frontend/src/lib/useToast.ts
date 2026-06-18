'use client';

import { useCallback, useState } from 'react';
import type { ToastMessage, ToastVariant } from '@/components/ui/Toast';

let nextId = 1;

export function useToast() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback((message: string, variant: ToastVariant = 'info') => {
    setToasts((prev) => [...prev, { id: nextId++, message, variant }]);
  }, []);

  return { toasts, showToast, dismissToast };
}
