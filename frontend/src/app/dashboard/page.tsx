'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { getToken } from '@/lib/auth';
import { getQueue, assignToMe, isConflictError } from '@/lib/api';
import { Table, TableHead, TableBody, TableRow, TableCell, TableEmpty } from '@/components/ui/Table';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import DuplicateBadge from '@/components/DuplicateBadge';
import { ToastContainer } from '@/components/ui/Toast';
import { useToast } from '@/lib/useToast';
import { formatDuration } from '@/lib/format';
import type { QueueItem } from '@/types';

export default function QueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [takingId, setTakingId] = useState<string | null>(null);
  const { toasts, showToast, dismissToast } = useToast();

  const fetchQueue = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setItems(await getQueue(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load queue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  async function handleTake(item: QueueItem) {
    const token = getToken();
    if (!token) return;
    setTakingId(item.id);
    try {
      await assignToMe(token, item.id, item.version);
      showToast(`Lead ${item.lead_number} is now yours.`, 'success');
      await fetchQueue();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — refreshing the queue.', 'warning');
        await fetchQueue();
      } else {
        showToast(err instanceof Error ? err.message : 'Failed to take lead.', 'error');
      }
    } finally {
      setTakingId(null);
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Queue</h1>
          {!loading && !error && (
            <p className="mt-1 text-sm text-gray-500">
              {items.length} unassigned lead{items.length !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={fetchQueue} className="text-xs">
          Refresh
        </Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Spinner />
        </div>
      )}

      {error && <Alert variant="error">{error}</Alert>}

      {!loading && !error && (
        <Table>
          <TableHead columns={['Lead #', 'Name', 'Email', 'Age', 'Flags', 'Action']} />
          <TableBody>
            {items.length === 0 ? (
              <TableEmpty message="The queue is empty." colSpan={6} />
            ) : (
              items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium text-gray-900">
                    <Link
                      href={`/dashboard/${item.id}`}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {item.lead_number}
                    </Link>
                  </TableCell>
                  <TableCell className="text-gray-900">
                    {item.first_name} {item.last_name}
                  </TableCell>
                  <TableCell>{item.email}</TableCell>
                  <TableCell className="text-gray-500">{formatDuration(item.age_seconds)}</TableCell>
                  <TableCell>{item.is_potential_duplicate && <DuplicateBadge />}</TableCell>
                  <TableCell>
                    <Button
                      variant="primary"
                      loading={takingId === item.id}
                      onClick={() => handleTake(item)}
                      className="px-3 py-1.5 text-xs"
                    >
                      Take
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
