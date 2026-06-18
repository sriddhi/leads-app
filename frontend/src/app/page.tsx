import LeadForm from '@/components/LeadForm';

export default function HomePage() {
  return (
    <main className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-lg">
        {/* Header Card */}
        <div className="relative overflow-hidden rounded-t-2xl bg-brand-700 px-8 py-9 text-white shadow-lg">
          <div className="absolute -right-10 -top-10 h-40 w-40 rounded-full bg-accent-500/20" />
          <div className="absolute right-16 bottom-0 h-20 w-20 rounded-full bg-accent-400/10" />
          <div className="relative">
            <span className="inline-block h-1 w-10 rounded-full bg-accent-400" />
            <h1 className="mt-4 text-2xl font-bold tracking-tight">Let&apos;s get started</h1>
            <p className="mt-1 text-sm text-brand-100">
              Tell us a little about you and share your resume — we&apos;ll take it from here.
            </p>
          </div>
        </div>

        {/* Form Card */}
        <div className="rounded-b-2xl border border-t-0 border-black/5 bg-white px-8 py-8 shadow-lg">
          <LeadForm />
        </div>
      </div>
    </main>
  );
}
