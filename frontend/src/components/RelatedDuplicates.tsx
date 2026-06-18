'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { getToken } from '@/lib/auth';
import { getRelatedLeads, transitionRelated } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import StatusBadge from '@/components/StatusBadge';
import Button from '@/components/ui/Button';
import type { RelatedLeadItem } from '@/types';

/**
 * Other OPEN leads in this lead's duplicate cluster. The attorney can select some and either
 * assign them to themselves or mark them reached out in one action — each transition records an
 * audit note referencing this (parent) case number. Duplicates are never merged.
 */
export default function RelatedDuplicates({
  leadId,
  parentNumber,
  onChanged,
}: {
  leadId: string;
  parentNumber: string | null;
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<RelatedLeadItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<{ ok: boolean; text: string }[]>([]);

  const load = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getRelatedLeads(token, leadId);
      setItems(data);
      setSelected((prev) => new Set([...prev].filter((id) => data.some((d) => d.id === id))));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load related leads.');
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelected((prev) =>
      prev.size === items.length ? new Set() : new Set(items.map((i) => i.id)),
    );

  async function apply(action: 'assign' | 'reached_out') {
    const token = getToken();
    if (!token || selected.size === 0) return;
    setBusy(true);
    setResults([]);
    try {
      const res = await transitionRelated(token, leadId, action, [...selected], note || undefined);
      setResults(
        res.map((r) => ({ ok: r.ok, text: `${r.lead_number ?? r.id.slice(0, 8)}: ${r.detail}` })),
      );
      setNote('');
      await load();
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Bulk action failed.');
    } finally {
      setBusy(false);
    }
  }

  // Nothing to show if there are no open siblings in the cluster.
  if (!loading && !error && items.length === 0) return null;

  return (
    <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50/40 p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-brand-800">
          Related open cases (possible duplicates)
        </h2>
        {items.length > 0 && (
          <button
            type="button"
            onClick={toggleAll}
            className="text-xs text-accent-700 hover:underline"
          >
            {selected.size === items.length ? 'Clear all' : 'Select all'}
          </button>
        )}
      </div>

      <p className="mb-3 text-xs text-gray-600">
        These open leads share contact details with{' '}
        <span className="font-medium">{parentNumber ?? 'this case'}</span>. Select any to transition
        together — an audit note will reference {parentNumber ?? 'the parent case'}.
      </p>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && items.length > 0 && (
        <ul className="divide-y divide-amber-100">
          {items.map((it) => (
            <li key={it.id} className="flex items-center justify-between py-2 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={selected.has(it.id)}
                  onChange={() => toggle(it.id)}
                  className="accent-accent-600"
                />
                <span>
                  <span className="font-medium text-gray-800">{it.lead_number}</span>{' '}
                  <span className="text-gray-600">
                    {it.first_name} {it.last_name}
                  </span>{' '}
                  <span className="text-gray-400">· {formatDateTime(it.created_at)}</span>
                </span>
              </label>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-500">
                  {it.assignee_id ? 'assigned' : 'unassigned'}
                </span>
                <StatusBadge status={it.status} />
              </div>
            </li>
          ))}
        </ul>
      )}

      {items.length > 0 && (
        <div className="mt-4 space-y-3">
          <input
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Optional note (added to the audit reference)"
            className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm focus:border-accent-500 focus:outline-none"
          />
          <div className="flex flex-wrap gap-3">
            <Button
              variant="primary"
              disabled={selected.size === 0}
              loading={busy}
              onClick={() => apply('assign')}
              className="text-xs"
            >
              Assign selected to me ({selected.size})
            </Button>
            <Button
              variant="secondary"
              disabled={selected.size === 0}
              loading={busy}
              onClick={() => apply('reached_out')}
              className="text-xs"
            >
              Mark selected reached out ({selected.size})
            </Button>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs">
          {results.map((r, i) => (
            <li key={i} className={r.ok ? 'text-green-700' : 'text-amber-700'}>
              {r.ok ? '✓' : '⚠'} {r.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
