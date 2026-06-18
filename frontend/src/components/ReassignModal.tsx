'use client';

import React, { useEffect, useState } from 'react';
import Modal from '@/components/ui/Modal';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import { getToken } from '@/lib/auth';
import { adminGetAttorneys } from '@/lib/api';
import type { AttorneyCapacity } from '@/types';

interface ReassignModalProps {
  open: boolean;
  onClose: () => void;
  /** assignee_id is null when "Unassign" is chosen. */
  onSubmit: (assigneeId: string | null, reason: string) => Promise<void>;
}

const UNASSIGN_VALUE = '__unassign__';

export default function ReassignModal({ open, onClose, onSubmit }: ReassignModalProps) {
  const [attorneys, setAttorneys] = useState<AttorneyCapacity[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(UNASSIGN_VALUE);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const token = getToken();
    if (!token) return;
    setLoadingList(true);
    setListError(null);
    setSelected(UNASSIGN_VALUE);
    setReason('');
    setSubmitError(null);
    adminGetAttorneys(token)
      .then(setAttorneys)
      .catch((err) =>
        setListError(err instanceof Error ? err.message : 'Failed to load attorneys.')
      )
      .finally(() => setLoadingList(false));
  }, [open]);

  async function handleConfirm() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      await onSubmit(selected === UNASSIGN_VALUE ? null : selected, reason.trim());
      onClose();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Reassignment failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Reassign lead"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" loading={submitting} onClick={handleConfirm}>
            Confirm
          </Button>
        </>
      }
    >
      {loadingList ? (
        <div className="flex justify-center py-6">
          <Spinner className="h-6 w-6 text-blue-600" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {listError && <Alert variant="error">{listError}</Alert>}
          <div className="flex flex-col gap-1">
            <label htmlFor="reassign-attorney" className="text-sm font-medium text-gray-700">
              Assign to
            </label>
            <select
              id="reassign-attorney"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm outline-none transition-colors focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              <option value={UNASSIGN_VALUE}>Unassign (return to queue)</option>
              {attorneys.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.open}/{a.max_open_cases})
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="reassign-reason" className="text-sm font-medium text-gray-700">
              Reason (optional)
            </label>
            <textarea
              id="reassign-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm outline-none transition-colors focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              placeholder="Why is this lead being reassigned?"
            />
          </div>
          {submitError && <Alert variant="error">{submitError}</Alert>}
        </div>
      )}
    </Modal>
  );
}
