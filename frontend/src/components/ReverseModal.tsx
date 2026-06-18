'use client';

import React, { useEffect, useState } from 'react';
import Modal from '@/components/ui/Modal';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';

interface ReverseModalProps {
  open: boolean;
  onClose: () => void;
  /** Reason is required and guaranteed non-empty before onSubmit is called. */
  onSubmit: (reason: string) => Promise<void>;
}

export default function ReverseModal({ open, onClose, onSubmit }: ReverseModalProps) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setReason('');
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  async function handleConfirm() {
    if (reason.trim().length === 0) {
      setError('A reason is required to reverse this lead.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(reason.trim());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Reversal failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      open={open}
      title="Reverse reached-out status"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="danger" loading={submitting} onClick={handleConfirm}>
            Reverse
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-gray-600">
          This will move the lead back to the assigned state. Please record why.
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor="reverse-reason" className="text-sm font-medium text-gray-700">
            Reason <span className="text-red-600">*</span>
          </label>
          <textarea
            id="reverse-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={3}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm outline-none transition-colors focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            placeholder="Explain why this status is being reversed."
          />
        </div>
        {error && <Alert variant="error">{error}</Alert>}
      </div>
    </Modal>
  );
}
