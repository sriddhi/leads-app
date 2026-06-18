import React from 'react';

interface BadgeProps {
  children: React.ReactNode;
  variant?: 'yellow' | 'green' | 'gray' | 'red' | 'blue';
}

const variantClasses: Record<NonNullable<BadgeProps['variant']>, string> = {
  yellow: 'bg-yellow-100 text-yellow-800',
  green: 'bg-green-100 text-green-800',
  gray: 'bg-gray-100 text-gray-800',
  red: 'bg-red-100 text-red-800',
  blue: 'bg-blue-100 text-blue-800',
};

export default function Badge({ children, variant = 'gray' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${variantClasses[variant]}`}
    >
      {children}
    </span>
  );
}
