'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { getToken } from '@/lib/auth';
import {
  adminGetMetrics,
  adminGetAttorneys,
  adminSetCapacity,
  adminToggleAutoAssign,
  isConflictError,
} from '@/lib/api';
import { Table, TableHead, TableBody, TableRow, TableCell, TableEmpty } from '@/components/ui/Table';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import { ToastContainer } from '@/components/ui/Toast';
import { useToast } from '@/lib/useToast';
import { formatDuration } from '@/lib/format';
import type { Metrics, AttorneyCapacity } from '@/types';

export default function AdminOverviewPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [attorneys, setAttorneys] = useState<AttorneyCapacity[]>([]);
  const [autoAssign, setAutoAssign] = useState(false);
  const [togglingAuto, setTogglingAuto] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [savingId, setSavingId] = useState<string | null>(null);

  const { toasts, showToast, dismissToast } = useToast();

  const fetchAll = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const [m, a] = await Promise.all([adminGetMetrics(token), adminGetAttorneys(token)]);
      setMetrics(m);
      setAttorneys(a);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  async function handleToggleAuto() {
    const token = getToken();
    if (!token) return;
    const next = !autoAssign;
    setTogglingAuto(true);
    try {
      const res = await adminToggleAutoAssign(token, next);
      setAutoAssign(res.enabled);
      showToast(`Auto-assign ${res.enabled ? 'enabled' : 'disabled'}.`, 'success');
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to toggle auto-assign.', 'error');
    } finally {
      setTogglingAuto(false);
    }
  }

  function startEdit(att: AttorneyCapacity) {
    setEditingId(att.id);
    setEditValue(String(att.max_open_cases));
  }

  async function saveEdit(att: AttorneyCapacity) {
    const token = getToken();
    if (!token) return;
    const parsed = Number(editValue);
    if (!Number.isInteger(parsed) || parsed < 0) {
      showToast('Capacity must be a non-negative whole number.', 'error');
      return;
    }
    setSavingId(att.id);
    try {
      const updated = await adminSetCapacity(token, att.id, parsed);
      setAttorneys((prev) => prev.map((a) => (a.id === att.id ? updated : a)));
      setEditingId(null);
      showToast(`Updated capacity for ${att.name}.`, 'success');
    } catch (err) {
      if (isConflictError(err)) {
        showToast('Data changed — refreshing.', 'warning');
        await fetchAll();
        setEditingId(null);
      } else {
        showToast(err instanceof Error ? err.message : 'Failed to update capacity.', 'error');
      }
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Overview</h1>
        <Button variant="secondary" onClick={fetchAll} className="text-xs">
          Refresh
        </Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Spinner />
        </div>
      )}

      {error && <Alert variant="error">{error}</Alert>}

      {!loading && !error && metrics && (
        <>
          {/* Metric cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <MetricCard label="Queue Depth" value={String(metrics.queue_depth)} />
            <MetricCard
              label="Oldest Queued"
              value={formatDuration(metrics.oldest_queued_age_seconds)}
            />
            <MetricCard label="In Progress" value={String(metrics.in_progress)} />
            <MetricCard label="Reached Out" value={String(metrics.reached_out)} />
            <MetricCard
              label="Reached Out (1h)"
              value={String(metrics.reached_out_last_hour)}
            />
          </div>

          {/* Auto-assign toggle */}
          <div className="mt-8 flex items-center justify-between rounded-xl border border-gray-200 bg-white px-6 py-4 shadow-sm">
            <div>
              <p className="text-sm font-semibold text-gray-900">Auto-assign</p>
              <p className="text-sm text-gray-500">
                Automatically route queued leads to available attorneys.
              </p>
            </div>
            <button
              type="button"
              onClick={handleToggleAuto}
              disabled={togglingAuto}
              aria-pressed={autoAssign}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors disabled:opacity-50 ${
                autoAssign ? 'bg-blue-600' : 'bg-gray-300'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  autoAssign ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          {/* Capacity table */}
          <div className="mt-8">
            <h2 className="mb-3 text-lg font-semibold text-gray-900">Attorney Capacity</h2>
            <Table>
              <TableHead columns={['Attorney', 'Open / Cap', 'Utilization', 'Max Open', '']} />
              <TableBody>
                {attorneys.length === 0 ? (
                  <TableEmpty message="No attorneys configured." colSpan={5} />
                ) : (
                  attorneys.map((att) => {
                    const utilization =
                      att.max_open_cases > 0 ? att.open / att.max_open_cases : 0;
                    const pct = Math.min(100, Math.round(utilization * 100));
                    return (
                      <TableRow key={att.id}>
                        <TableCell className="font-medium text-gray-900">{att.name}</TableCell>
                        <TableCell>
                          {att.open} / {att.max_open_cases}
                        </TableCell>
                        <TableCell className="w-48">
                          <div className="flex items-center gap-2">
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200">
                              <div
                                className={`h-full rounded-full ${
                                  pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-blue-600'
                                }`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span className="w-10 text-right text-xs text-gray-500">{pct}%</span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {editingId === att.id ? (
                            <input
                              type="number"
                              min={0}
                              value={editValue}
                              onChange={(e) => setEditValue(e.target.value)}
                              className="w-20 rounded-md border border-gray-300 px-2 py-1 text-sm shadow-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                            />
                          ) : (
                            att.max_open_cases
                          )}
                        </TableCell>
                        <TableCell>
                          {editingId === att.id ? (
                            <div className="flex gap-2">
                              <Button
                                variant="primary"
                                loading={savingId === att.id}
                                onClick={() => saveEdit(att)}
                                className="px-3 py-1.5 text-xs"
                              >
                                Save
                              </Button>
                              <Button
                                variant="secondary"
                                onClick={() => setEditingId(null)}
                                className="px-3 py-1.5 text-xs"
                              >
                                Cancel
                              </Button>
                            </div>
                          ) : (
                            <Button
                              variant="secondary"
                              onClick={() => startEdit(att)}
                              className="px-3 py-1.5 text-xs"
                            >
                              Edit
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</p>
      <p className="mt-2 text-2xl font-bold text-gray-900">{value}</p>
    </div>
  );
}
