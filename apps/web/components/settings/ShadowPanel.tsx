"use client";

import { useState } from "react";
import { Info, Loader2, Save } from "lucide-react";
import { cn } from "@/lib/utils";

export interface ShadowSettings {
  shadow_min_dte: number;
  shadow_max_dte: number;
  shadow_max_contracts: number;
  shadow_max_risk_usd: number;
  shadow_allow_earnings: boolean;
  score_threshold: number;
}

interface ShadowPanelProps {
  initial: ShadowSettings;
  onSave?: (values: ShadowSettings) => Promise<void>;
}

interface FieldConfig {
  key: keyof ShadowSettings;
  label: string;
  hint: string;
  type: "number" | "boolean";
  min?: number;
  max?: number;
  step?: number;
}

const FIELDS: FieldConfig[] = [
  {
    key: "shadow_min_dte",
    label: "Min DTE (shadow)",
    hint: "Relaxed from the live Tiny limit of 7 days.",
    type: "number",
    min: 1,
    max: 7,
    step: 1,
  },
  {
    key: "shadow_max_dte",
    label: "Max DTE (shadow)",
    hint: "Upper expiry window for shadow signal discovery.",
    type: "number",
    min: 7,
    max: 60,
    step: 1,
  },
  {
    key: "shadow_max_contracts",
    label: "Max contracts (shadow)",
    hint: "Relaxed from the live Tiny limit of 1 contract.",
    type: "number",
    min: 1,
    max: 3,
    step: 1,
  },
  {
    key: "shadow_max_risk_usd",
    label: "Max risk / trade (shadow)",
    hint: "Dollar cap for shadow signals. Relaxed from the $5 live limit.",
    type: "number",
    min: 5,
    max: 15,
    step: 1,
  },
  {
    key: "score_threshold",
    label: "Options Score threshold",
    hint: "Minimum score (0–10) for a contract to qualify as a signal.",
    type: "number",
    min: 6.0,
    max: 9.0,
    step: 0.5,
  },
  {
    key: "shadow_allow_earnings",
    label: "Allow earnings plays (shadow)",
    hint: "Permit earnings-window contracts in shadow signals only.",
    type: "boolean",
  },
];

function NumberField({
  config,
  value,
  onChange,
}: {
  config: FieldConfig;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <label className="font-mono text-[11px] text-zinc-400">{config.label}</label>
        <span className="font-mono text-xs tabular-nums text-zinc-200">{value}</span>
      </div>
      <input
        type="range"
        min={config.min}
        max={config.max}
        step={config.step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1 w-full cursor-pointer appearance-none rounded-full bg-zinc-700 accent-violet-500"
      />
      <div className="flex justify-between">
        <span className="font-mono text-[10px] text-zinc-700">{config.min}</span>
        <span className="font-mono text-[10px] text-zinc-700">{config.max}</span>
      </div>
      <p className="text-[10px] text-zinc-600">{config.hint}</p>
    </div>
  );
}

function BoolField({
  config,
  value,
  onChange,
}: {
  config: FieldConfig;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3">
      <div>
        <p className="font-mono text-[11px] text-zinc-400">{config.label}</p>
        <p className="mt-0.5 text-[10px] text-zinc-600">{config.hint}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={cn(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors focus:outline-none",
          value ? "bg-violet-600" : "bg-zinc-700",
        )}
        aria-checked={value}
        role="switch"
      >
        <span
          className={cn(
            "absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            value ? "translate-x-4" : "translate-x-0.5",
          )}
        />
      </button>
    </div>
  );
}

export function ShadowPanel({ initial, onSave }: ShadowPanelProps) {
  const [values, setValues] = useState<ShadowSettings>(initial);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dirty = JSON.stringify(values) !== JSON.stringify(initial);

  async function handleSave() {
    if (!onSave) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(values);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function set<K extends keyof ShadowSettings>(key: K, val: ShadowSettings[K]) {
    setValues((prev) => ({ ...prev, [key]: val }));
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="font-mono text-xs uppercase tracking-widest text-zinc-400">
          Shadow Testing
        </h3>
        <p className="mt-1 text-xs text-zinc-600">
          Relaxed parameters used during shadow mode signal discovery. These never apply to live
          order submission.
        </p>
      </div>

      <div className="flex items-start gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-4 py-3">
        <Info className="mt-0.5 h-3 w-3 shrink-0 text-amber-400" strokeWidth={1.5} />
        <p className="text-[11px] text-amber-300/80">
          Shadow overrides only affect the auto-scanner and workbench analysis. Real order
          constraints always use hardcoded tier limits regardless of these settings.
        </p>
      </div>

      <div className="space-y-5">
        {FIELDS.map((field) =>
          field.type === "number" ? (
            <NumberField
              key={field.key}
              config={field}
              value={values[field.key] as number}
              onChange={(v) => set(field.key, v as ShadowSettings[typeof field.key])}
            />
          ) : (
            <BoolField
              key={field.key}
              config={field}
              value={values[field.key] as boolean}
              onChange={(v) => set(field.key, v as ShadowSettings[typeof field.key])}
            />
          ),
        )}
      </div>

      {error && <p className="font-mono text-xs text-rose-400">{error}</p>}

      <div className="flex items-center justify-between border-t border-zinc-800 pt-4">
        {savedAt && !dirty ? (
          <span className="font-mono text-[10px] text-zinc-600">Saved {savedAt}</span>
        ) : (
          <span />
        )}
        <button
          type="button"
          disabled={!dirty || saving || !onSave}
          onClick={handleSave}
          className={cn(
            "flex items-center gap-2 font-mono text-xs transition-colors",
            dirty && !saving
              ? "text-zinc-300 hover:text-white"
              : "cursor-not-allowed text-zinc-700",
          )}
        >
          {saving ? (
            <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.5} />
          ) : (
            <Save className="h-3 w-3" strokeWidth={1.5} />
          )}
          {saving ? "Saving…" : "Save changes"}
        </button>
      </div>
    </div>
  );
}
