"use client";

import { useState } from "react";

import { api } from "@/lib/api";

type State =
  | { kind: "idle" }
  | { kind: "calling" }
  | { kind: "ok"; sid: string; to: string }
  | { kind: "error"; message: string };

export function TriggerCallButton() {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function onClick() {
    setState({ kind: "calling" });
    try {
      const res = await api.triggerDemoCall();
      setState({ kind: "ok", sid: res.call_sid, to: res.to });
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={onClick}
        disabled={state.kind === "calling"}
        className="inline-flex w-fit items-center gap-2 rounded-full bg-neutral-900 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-neutral-700 disabled:opacity-50 dark:bg-white dark:text-neutral-900 dark:hover:bg-neutral-200"
      >
        {state.kind === "calling" ? "Dialing…" : "📞 Start a check-in call"}
      </button>

      {state.kind === "ok" && (
        <p className="text-sm text-green-700 dark:text-green-400">
          Calling {state.to} — your phone should ring.{" "}
          <span className="font-mono text-xs text-neutral-500">{state.sid}</span>
        </p>
      )}
      {state.kind === "error" && (
        <p className="text-sm text-red-600 dark:text-red-400">{state.message}</p>
      )}
    </div>
  );
}
