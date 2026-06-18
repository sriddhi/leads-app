'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { getToken } from '@/lib/auth';
import { adminGetAttorneyTime } from '@/lib/api';
import { Table, TableHead, TableBody, TableRow, TableCell, TableEmpty } from '@/components/ui/Table';
import Button from '@/components/ui/Button';
import Alert from '@/components/ui/Alert';
import Spinner from '@/components/ui/Spinner';
import { formatDuration } from '@/lib/format';
import type { AttorneyTimeRow } from '@/types';

export default function AttorneyTimePage() {
  const [rows, setRows] = useState<AttorneyTimeRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRows = useCallback(async () => {
    const token = getToken();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setRows(await adminGetAttorneyTime(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load attorney time.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRows();
  }, [fetchRows]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Attorney Time</h1>
          <p className="mt-1 text-sm text-gray-500">
            How long each attorney has held leads and how quickly they reach out.
          </p>
        </div>
        <Button variant="secondary" onClick={fetchRows} className="text-xs">
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
          <TableHead
            columns={[
              'Attorney',
              'Cases Handled',
              'Total Holding Time',
              'Avg Time to Reached Out',
              'Current Open Load',
              'Oldest Open Age',
            ]}
          />
          <TableBody>
            {rows.length === 0 ? (
              <TableEmpty message="No attorney activity yet." colSpan={6} />
            ) : (
              rows.map((row) => (
                <TableRow key={row.attorney_id}>
                  <TableCell className="font-medium text-gray-900">{row.name}</TableCell>
                  <TableCell>{row.cases_handled}</TableCell>
                  <TableCell>{formatDuration(row.total_holding_seconds)}</TableCell>
                  <TableCell>{formatDuration(row.avg_time_to_reached_out_seconds)}</TableCell>
                  <TableCell>{row.current_open_load}</TableCell>
                  <TableCell>{formatDuration(row.oldest_open_age_seconds)}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
