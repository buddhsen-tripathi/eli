import { TriggerCallButton } from "@/components/trigger-call-button";

export default function Home() {
  return (
    <main className="mx-auto flex min-h-full max-w-2xl flex-col justify-center gap-6 px-6 py-16">
      <div className="flex flex-col gap-4">
        <p className="font-mono text-xs uppercase tracking-widest text-neutral-500">
          arya · post-op care
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">Clinician dashboard</h1>
        <p className="text-neutral-600 dark:text-neutral-400">
          Voice check-ins for recently-discharged elderly patients — with automatic
          recaps to their loved ones. This is the care-team view.
        </p>
      </div>

      <div className="rounded-xl border border-neutral-200 p-5 dark:border-neutral-800">
        <p className="mb-3 text-sm text-neutral-600 dark:text-neutral-400">
          Trigger a test check-in to the number configured on the backend
          (<code className="font-mono text-xs">DESTINATION_PHONE_NUMBER</code>).
        </p>
        <TriggerCallButton />
      </div>
    </main>
  );
}
