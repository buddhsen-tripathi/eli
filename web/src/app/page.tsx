export default function Home() {
  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col justify-center gap-4 px-6 py-16">
      <p className="font-mono text-xs uppercase tracking-widest text-neutral-500">
        arya · post-op care
      </p>
      <h1 className="text-3xl font-semibold tracking-tight">Clinician dashboard</h1>
      <p className="text-neutral-600 dark:text-neutral-400">
        Voice check-ins for recently-discharged elderly patients — with automatic
        recaps to their loved ones. This is the care-team view. Patients, caregivers,
        calls, and triage are served by the FastAPI backend in{" "}
        <code className="rounded bg-neutral-100 px-1 py-0.5 font-mono text-sm dark:bg-neutral-800">
          ../api
        </code>
        . Start building here.
      </p>
    </main>
  );
}
