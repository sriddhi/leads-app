import React from 'react';

export function Table({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 shadow-sm">
      <table className="min-w-full divide-y divide-gray-200">{children}</table>
    </div>
  );
}

export function TableHead({ columns }: { columns: string[] }) {
  return (
    <thead className="bg-gray-50">
      <tr>
        {columns.map((col) => (
          <th
            key={col}
            className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500"
          >
            {col}
          </th>
        ))}
      </tr>
    </thead>
  );
}

export function TableBody({ children }: { children: React.ReactNode }) {
  return <tbody className="divide-y divide-gray-200 bg-white">{children}</tbody>;
}

export function TableRow({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <tr className={`transition-colors hover:bg-gray-50 ${className}`}>{children}</tr>;
}

export function TableCell({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <td className={`whitespace-nowrap px-6 py-4 text-sm text-gray-700 ${className}`}>{children}</td>;
}

export function TableEmpty({ message, colSpan }: { message: string; colSpan: number }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-6 py-16 text-center text-sm text-gray-500">
        {message}
      </td>
    </tr>
  );
}
