'use client';

import React, { useEffect, useRef, useState } from 'react';
import { getToken } from '@/lib/auth';
import { adminGetAudit, openAuditStream } from '@/lib/api';
import { Table, TableHead, TableBody, TableRow, TableCell, TableEmpty } from '@/components/ui/Table';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import Badge from '@/components/ui/Badge';
import { formatTime } from '@/lib/format';
import type { AuditEvent } from '@/types';

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    const token = getToken();
    if (!token) return;

    let source: EventSource | null = null;

    adminGetAudit(token)
      .then((data) => {
        seenIds.current = new Set(data.items.map((e) => e.id));
        setEvents(data.items);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load audit log.');
      })
      .finally(() => {
        setLoading(false);
        source = openAuditStream(token, (event) => {
          if (seenIds.current.has(event.id)) return;
          seenIds.current.add(event.id);
          setEvents((prev) => [event, ...prev]);
        });
        source.onopen = () => setLive(true);
        source.onerror = () => setLive(false);
      });

    return () => {
      if (source) source.close();
    };
  }, []);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Audit Log</h1>
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${live ? 'animate-pulse bg-green-500' : 'bg-gray-300'}`}
          />
          <span className="text-sm text-gray-500">{live ? 'Live' : 'Offline'}</span>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-16">
          <Spinner />
        </div>
      )}

      {error && <Alert variant="error">{error}</Alert>}

      {!loading && !error && (
        <Table>
          <TableHead columns={['Time', 'Action', 'Actor', 'Lead', 'Reason', 'IP']} />
          <TableBody>
            {events.length === 0 ? (
              <TableEmpty message="No audit events yet." colSpan={6} />
            ) : (
              events.map((e) => (
                <TableRow key={e.id}>
                  <TableCell className="text-gray-500">{formatTime(e.created_at)}</TableCell>
                  <TableCell>
                    <Badge variant="blue">{e.action}</Badge>
                  </TableCell>
                  <TableCell className="text-gray-700">{e.actor_kind}</TableCell>
                  <TableCell className="font-mono text-xs text-gray-700">{e.lead_id}</TableCell>
                  <TableCell className="text-gray-700">{e.reason ?? '—'}</TableCell>
                  <TableCell className="text-gray-500">{e.ip ?? '—'}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
