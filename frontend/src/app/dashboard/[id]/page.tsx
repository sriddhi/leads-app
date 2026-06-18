'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getToken } from '@/lib/auth';
import {
  getLeadDetail,
  markReachedOut,
  reverse,
  reassign,
  isConflictError,
} from '@/lib/api';
import StatusBadge from '@/components/StatusBadge';
import DuplicateBadge from '@/components/DuplicateBadge';
import Timeline from '@/components/Timeline';
import CaseHistory from '@/components/CaseHistory';
import RelatedDuplicates from '@/components/RelatedDuplicates';
import ReverseModal from '@/components/ReverseModal';
import ReassignModal from '@/components/ReassignModal';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import { ToastContainer } from '@/components/ui/Toast';
import { useToast } from '@/lib/useToast';
import { formatDateTime } from '@/lib/format';
import type { LeadDetail } from '@/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

export default function LeadDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [lead, setLead] = useState<LeadDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [updating, setUpdating] = useState(false);
  const [reverseOpen, setReverseOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);
  const { toasts, showToast, dismissToast } = useToast();

  const fetchLead = useCallback(async () => {
    const token = getToken();
    if (!token) {
      router.push('/login');
      return;
    }
    try {
      setLead(await getLeadDetail(token, id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load lead.');
    } finally {
      setLoading(false);
    }
  }, [id, router]);

  useEffect(() => {
    fetchLead();
  }, [fetchLead]);

  async function handleMarkReachedOut() {
    const token = getToken();
    if (!token || !lead) return;
    setUpdating(true);
    try {
      await markReachedOut(token, lead.id, lead.version);
      showToast('Marked as reached out.', 'success');
      await fetchLead();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — reloading.', 'warning');
        await fetchLead();
      } else {
        showToast(err instanceof Error ? err.message : 'Failed to update status.', 'error');
      }
    } finally {
      setUpdating(false);
    }
  }

  async function handleReverseSubmit(reason: string) {
    const token = getToken();
    if (!token || !lead) return;
    try {
      await reverse(token, lead.id, lead.version, reason);
      showToast('Reversed reached-out status.', 'success');
      await fetchLead();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — reloading.', 'warning');
        await fetchLead();
      }
      throw err;
    }
  }

  async function handleReassignSubmit(assigneeId: string | null, reason: string) {
    const token = getToken();
    if (!token || !lead) return;
    try {
      await reassign(token, lead.id, lead.version, assigneeId, reason || undefined);
      showToast('Lead reassigned.', 'success');
      await fetchLead();
    } catch (err) {
      if (isConflictError(err)) {
        showToast('This lead changed — reloading.', 'warning');
        await fetchLead();
      }
      throw err;
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spinner />
      </div>
    );
  }

  if (error && !lead) {
    return <Alert variant="error">{error}</Alert>;
  }

  if (!lead) return null;

  return (
    <div className="max-w-3xl">
      <Link
        href="/dashboard"
        className="mb-6 inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-800 hover:underline"
      >
        ← Back to Queue
      </Link>

      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-gray-900">
              {lead.first_name} {lead.last_name}
            </h1>
            <span className="text-sm text-gray-400">{lead.lead_number}</span>
          </div>
          <p className="mt-1 text-sm text-gray-500">{lead.email}</p>
        </div>
        <div className="flex items-center gap-2">
          {lead.is_potential_duplicate && <DuplicateBadge />}
          <StatusBadge status={lead.status} />
        </div>
      </div>

      {/* Detail card */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
        <dl className="divide-y divide-gray-100">
          <DetailRow label="Lead Number" value={lead.lead_number} />
          <DetailRow label="First Name" value={lead.first_name} />
          <DetailRow label="Last Name" value={lead.last_name} />
          <DetailRow label="Email Address" value={lead.email} />
          <DetailRow label="Phone" value={lead.phone || '—'} />
          <DetailRow label="Message" value={lead.message || '—'} />
          <DetailRow label="Assignee" value={lead.assignee_name ?? 'Unassigned'} />
          <DetailRow
            label="Resume"
            value={
              <a
                href={`${API_URL}/api/v1/leads/${lead.id}/resume?token=${getToken() ?? ''}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:text-blue-800 hover:underline"
              >
                {lead.resume_original_filename}
              </a>
            }
          />
          <DetailRow label="Status" value={<StatusBadge status={lead.status} />} />
          {lead.is_potential_duplicate && (
            <DetailRow
              label="Duplicate"
              value={
                lead.duplicate_of ? (
                  <Link
                    href={`/dashboard/${lead.duplicate_of}`}
                    className="text-blue-600 hover:text-blue-800 hover:underline"
                  >
                    Possible duplicate of an existing lead — view original
                  </Link>
                ) : (
                  'Flagged as a possible duplicate'
                )
              }
            />
          )}
          <DetailRow label="Submitted" value={formatDateTime(lead.created_at)} />
          <DetailRow label="Last Updated" value={formatDateTime(lead.updated_at)} />
        </dl>
      </div>

      {/* Timeline */}
      <div className="mt-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-gray-500">
          Timeline
        </h2>
        <Timeline periods={lead.timeline} />
      </div>

      {/* Case history (phone/email/name matches, last 6 months) */}
      <CaseHistory leadId={id} />

      {/* Related open cases in the same duplicate cluster — bulk assign / reach-out */}
      <RelatedDuplicates leadId={id} parentNumber={lead.lead_number} onChanged={fetchLead} />

      {/* Actions */}
      <div className="mt-8 flex flex-wrap gap-3">
        {lead.status === 'PENDING' && (
          <Button variant="primary" loading={updating} onClick={handleMarkReachedOut}>
            Mark as Reached Out
          </Button>
        )}
        {lead.status === 'REACHED_OUT' && (
          <Button variant="danger" onClick={() => setReverseOpen(true)}>
            Reverse Reached Out
          </Button>
        )}
        <Button variant="secondary" onClick={() => setReassignOpen(true)}>
          Reassign
        </Button>
      </div>

      <ReverseModal
        open={reverseOpen}
        onClose={() => setReverseOpen(false)}
        onSubmit={handleReverseSubmit}
      />
      <ReassignModal
        open={reassignOpen}
        onClose={() => setReassignOpen(false)}
        onSubmit={handleReassignSubmit}
      />

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="grid grid-cols-3 gap-4 px-6 py-4">
      <dt className="text-sm font-medium text-gray-500">{label}</dt>
      <dd className="col-span-2 text-sm text-gray-900">{value}</dd>
    </div>
  );
}
