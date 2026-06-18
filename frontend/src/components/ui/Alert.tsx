import React from 'react';

interface AlertProps {
  variant?: 'error' | 'success' | 'info' | 'warning';
  children: React.ReactNode;
  className?: string;
}

const variantClasses: Record<NonNullable<AlertProps['variant']>, string> = {
  error: 'border-red-200 bg-red-50 text-red-700',
  success: 'border-green-200 bg-green-50 text-green-700',
  info: 'border-blue-200 bg-blue-50 text-blue-700',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
};

export default function Alert({ variant = 'error', children, className = '' }: AlertProps) {
  return (
    <div
      role="alert"
      className={`rounded-md border px-4 py-3 text-sm ${variantClasses[variant]} ${className}`}
    >
      {children}
    </div>
  );
}
