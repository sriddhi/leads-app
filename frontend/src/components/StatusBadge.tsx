import Badge from '@/components/ui/Badge';
import type { LeadStatus, LeadState } from '@/types';

interface StatusBadgeProps {
  status: LeadStatus;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  if (status === 'PENDING') {
    return <Badge variant="yellow">Pending</Badge>;
  }
  return <Badge variant="green">Reached Out</Badge>;
}

interface StateBadgeProps {
  state: LeadState;
}

export function StateBadge({ state }: StateBadgeProps) {
  switch (state) {
    case 'QUEUED':
      return <Badge variant="yellow">Queued</Badge>;
    case 'ASSIGNED':
      return <Badge variant="blue">Assigned</Badge>;
    case 'REACHED_OUT':
      return <Badge variant="green">Reached Out</Badge>;
    default:
      return <Badge variant="gray">{state}</Badge>;
  }
}
