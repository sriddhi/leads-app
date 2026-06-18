import React from 'react';
import { StateBadge } from '@/components/StatusBadge';
import { formatDuration, formatDateTime } from '@/lib/format';
import type { StatePeriod } from '@/types';

interface TimelineProps {
  periods: StatePeriod[];
}

export default function Timeline({ periods }: TimelineProps) {
  if (periods.length === 0) {
    return <p className="text-sm text-gray-500">No timeline events yet.</p>;
  }

  return (
    <ol className="relative border-l border-gray-200 pl-6">
      {periods.map((period, idx) => (
        <li key={`${period.state}-${period.entered_at}-${idx}`} className="mb-6 last:mb-0">
          <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-white bg-blue-500" />
          <div className="flex flex-wrap items-center gap-2">
            <StateBadge state={period.state} />
            {period.assignee_name && (
              <span className="text-sm font-medium text-gray-700">{period.assignee_name}</span>
            )}
            <span className="text-xs text-gray-400">
              {formatDuration(period.duration_seconds)}
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            {formatDateTime(period.entered_at)}
            {period.exited_at ? ` → ${formatDateTime(period.exited_at)}` : ' → present'}
          </p>
        </li>
      ))}
    </ol>
  );
}
