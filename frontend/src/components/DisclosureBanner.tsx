import React from 'react';

export default function DisclosureBanner() {
  return (
    <div className="w-full border-b border-brand-100 bg-brand-50 px-4 py-1.5 text-center text-xs text-brand-700">
      <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-accent-500 align-middle" />
      <span className="align-middle">candidate interview with Alma — not business code</span>
    </div>
  );
}
