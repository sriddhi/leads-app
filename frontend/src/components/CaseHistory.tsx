'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { getToken } from '@/lib/auth';
import { getCaseHistory } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import StatusBadge from '@/components/StatusBadge';
import type { CaseHistoryItem } from '@/types';

const DIMS: { key: string; label: string }[] = [
  { key: 'phone', label: 'Phone' },
  { key: 'email', label: 'Email' },
  { key: 'first_name', label: 'First name' },
  { key: 'last_name', label: 'Last name' },
];

// Prior cases matching phone/email/name within the last 6 months. Default = phone OR email.
export default function CaseHistory({ leadId }: { leadId: string }) {
  const [dims, setDims] = useState<string[]>(['phone', 'email']);
  const [items, setItems] = useState<CaseHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await getCaseHistory(token, leadId, dims));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history.');
    } finally {
      setLoading(false);
    }
  }, [leadId, dims]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (key: string) =>
    setDims((prev) => (prev.includes(key) ? prev.filter((d) => d !== key) : [...prev, key]));

  return (
    <div className="mt-6 rounded-xl border border-black/5 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-brand-800">Case History (last 6 months)</h2>
        <div className="flex flex-wrap gap-3 text-xs text-gray-600">
          {DIMS.map((d) => (
            <label key={d.key} className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={dims.includes(d.key)}
                onChange={() => toggle(d.key)}
                className="accent-accent-600"
              />
              {d.label}
            </label>
          ))}
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="text-sm text-gray-400">No matching prior cases.</p>
      )}
      {!loading && !error && items.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {items.map((it) => (
            <li key={it.id} className="flex items-center justify-between py-2 text-sm">
              <div>
                <span className="font-medium text-gray-800">{it.lead_number}</span>{' '}
                <span className="text-gray-600">{it.first_name} {it.last_name}</span>{' '}
                <span className="text-gray-400">· {formatDateTime(it.created_at)}</span>
              </div>
              <div className="flex items-center gap-2">
                {it.matched_on.map((m) => (
                  <span key={m} className="rounded-full bg-accent-50 px-2 py-0.5 text-xs text-accent-700">
                    {m}
                  </span>
                ))}
                <StatusBadge status={it.status} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
