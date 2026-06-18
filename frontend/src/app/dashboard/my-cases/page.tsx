'use client';

import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { getToken } from '@/lib/auth';
import { getMe, getMyCases, markReachedOut, reassign, isConflictError } from '@/lib/api';
import { Table, TableHead, TableBody, TableRow, TableCell, TableEmpty } from '@/components/ui/Table';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import StatusBadge from '@/components/StatusBadge';
import DuplicateBadge from '@/components/DuplicateBadge';
import ReassignModal from '@/components/ReassignModal';
import { ToastContainer } from '@/components/ui/Toast';
import { useToast } from '@/lib/useToast';
import type { Lead } from '@/types';

export default function MyCasesPage() {
  const [cases, setCases] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actingId, setActingId] = useState<string | null>(null);
  const [reassignTarget, setReassignTarget] = useState<Lead | null>(null);
  const [firstName, setFirstName] = useState('');
  const { toasts, showToast, dismissToast } = useToast();

  const fetchCases = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setCases(await getMyCases(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load your cases.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCases();
    const token = getToken();
    if (token) {
      getMe(token)
        .then((u) => setFirstName(u.first_name?.trim() || u.full_name?.trim().split(/\s+/)[0] || ''))
        .catch(() => {});
    }
  }, [fetchCases]);

  async function handleReachedOut(lead: Lead) {
    const token = getToken();
    if (!token) return;
    setActingId(lead.id);
    try {
      await markReachedOut(token, lead.id, lead.version);
      showToast(`Marked ${lead.lead_number} as reached out.`, 'success');
      await fetchCases();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — refreshing your cases.', 'warning');
        await fetchCases();
      } else {
        showToast(err instanceof Error ? err.message : 'Failed to update status.', 'error');
      }
    } finally {
      setActingId(null);
    }
  }

  async function handleReassignSubmit(assigneeId: string | null, reason: string) {
    const token = getToken();
    if (!token || !reassignTarget) return;
    try {
      await reassign(token, reassignTarget.id, reassignTarget.version, assigneeId, reason || undefined);
      showToast(`Reassigned ${reassignTarget.lead_number}.`, 'success');
      await fetchCases();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — refreshing your cases.', 'warning');
        await fetchCases();
        throw err;
      }
      throw err;
    }
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {firstName ? `${firstName}'s Intakes` : 'My Intakes'}
          </h1>
          {!loading && !error && (
            <p className="mt-1 text-sm text-gray-500">
              {cases.length} open case{cases.length !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        <Button variant="secondary" onClick={fetchCases} className="text-xs">
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
          <TableHead columns={['Lead #', 'Name', 'Email', 'Status', 'Flags', 'Actions']} />
          <TableBody>
            {cases.length === 0 ? (
              <TableEmpty message="You have no open cases." colSpan={6} />
            ) : (
              cases.map((lead) => (
                <TableRow key={lead.id}>
                  <TableCell className="font-medium text-gray-900">
                    <Link
                      href={`/dashboard/${lead.id}`}
                      className="text-blue-600 hover:text-blue-800 hover:underline"
                    >
                      {lead.lead_number}
                    </Link>
                  </TableCell>
                  <TableCell className="text-gray-900">
                    {lead.first_name} {lead.last_name}
                  </TableCell>
                  <TableCell>{lead.email}</TableCell>
                  <TableCell>
                    <StatusBadge status={lead.status} />
                  </TableCell>
                  <TableCell>{lead.is_potential_duplicate && <DuplicateBadge />}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      {lead.status === 'PENDING' && (
                        <Button
                          variant="primary"
                          loading={actingId === lead.id}
                          onClick={() => handleReachedOut(lead)}
                          className="px-3 py-1.5 text-xs"
                        >
                          Mark Reached Out
                        </Button>
                      )}
                      <Button
                        variant="secondary"
                        onClick={() => setReassignTarget(lead)}
                        className="px-3 py-1.5 text-xs"
                      >
                        Reassign
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}

      <ReassignModal
        open={reassignTarget !== null}
        onClose={() => setReassignTarget(null)}
        onSubmit={handleReassignSubmit}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
