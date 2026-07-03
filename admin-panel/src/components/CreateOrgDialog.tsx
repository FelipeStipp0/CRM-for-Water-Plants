"use client";

import { useState, FormEvent } from "react";
import { api } from "@/lib/api";

interface Props {
  onCreated: () => void;
}

// O slug é o RUC da empresa, só com dígitos (vira nome do banco e usuario Mongo).
const rucToSlug = (ruc: string) => ruc.replace(/\D/g, "");

export function CreateOrgDialog({ onCreated }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [ruc, setRuc] = useState("");

  const slug = rucToSlug(ruc);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    if (slug.length < 2) {
      setError("Ingrese un RUC válido.");
      return;
    }
    setLoading(true);
    const form = new FormData(e.currentTarget);
    try {
      await api.createOrg({
        name: form.get("name") as string,
        slug,
        masterEmail: form.get("masterEmail") as string,
      });
      setOpen(false);
      setRuc("");
      onCreated();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Error al crear");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="bg-zinc-100 text-zinc-900 text-sm font-semibold px-4 py-2 rounded-lg hover:bg-white transition"
      >
        + Nueva organización
      </button>
    );
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 w-full max-w-md space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold text-lg">Nueva organización</h2>
          <button onClick={() => setOpen(false)} className="text-zinc-400 hover:text-zinc-200">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1">
            <label className="text-sm text-zinc-300">Nombre de la junta</label>
            <input
              name="name"
              required
              placeholder="Junta de Saneamiento ABC"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
          </div>
          <div className="space-y-1">
            <label className="text-sm text-zinc-300">RUC de la empresa <span className="text-zinc-500">(identificador único)</span></label>
            <input
              name="ruc"
              required
              value={ruc}
              onChange={(e) => setRuc(e.target.value)}
              placeholder="80012345-6"
              inputMode="numeric"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
            <p className="text-xs text-zinc-500">
              Identificador (slug):{" "}
              <span className="font-mono text-zinc-300">{slug || "—"}</span>
            </p>
          </div>
          <div className="space-y-1">
            <label className="text-sm text-zinc-300">Email del master</label>
            <input
              name="masterEmail"
              type="email"
              required
              placeholder="master@junta.com"
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-500"
            />
          </div>

          {error && <p className="text-red-400 text-sm">{error}</p>}

          <div className="flex gap-2 pt-1">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="flex-1 border border-zinc-700 text-sm py-2 rounded-lg hover:bg-zinc-800 transition"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 bg-zinc-100 text-zinc-900 font-semibold text-sm py-2 rounded-lg hover:bg-white transition disabled:opacity-50"
            >
              {loading ? "Creando..." : "Crear y enviar email"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
