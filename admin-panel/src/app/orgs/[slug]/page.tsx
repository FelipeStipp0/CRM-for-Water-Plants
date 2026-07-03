"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { api, OrgDetail } from "@/lib/api";

export default function OrgDetailPage() {
  const router = useRouter();
  const { slug } = useParams<{ slug: string }>();
  const [org, setOrg] = useState<OrgDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    api.getOrg(slug)
      .then(setOrg)
      .catch(() => router.push("/orgs"))
      .finally(() => setLoading(false));
  }, [slug]);

  async function handleToggleActive() {
    if (!org) return;
    await api.toggleActive(slug, !org.isActive);
    setOrg({ ...org, isActive: !org.isActive });
    setMsg(org.isActive ? "Organización desactivada" : "Organización activada");
  }

  async function handleResetPassword() {
    await api.resetPassword(slug);
    setMsg("Nueva contraseña enviada al email del master");
  }

  async function handleDelete() {
    const adminEmail = prompt("Ingrese su email para confirmar:");
    if (!adminEmail) return;
    await api.requestDelete(slug, adminEmail);
    setMsg("Email de confirmación enviado. La organización será eliminada en 30 días tras confirmar.");
  }

  if (loading) return <div className="p-8 text-zinc-400">Cargando...</div>;
  if (!org) return null;

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center gap-3">
        <button onClick={() => router.push("/orgs")} className="text-zinc-400 hover:text-zinc-200 text-sm">
          ← Volver
        </button>
        <h1 className="font-bold text-lg">{org.name}</h1>
        <span className={`text-xs px-2 py-0.5 rounded-full ${org.isActive ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"}`}>
          {org.isActive ? "Activa" : "Inactiva"}
        </span>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {msg && (
          <div className="bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-3 text-sm text-zinc-200">
            {msg}
          </div>
        )}

        {/* Info */}
        <section className="bg-zinc-900 rounded-xl border border-zinc-800 p-5 space-y-3">
          <h2 className="font-semibold text-zinc-200">Información</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-zinc-400">Slug:</span> <span className="font-mono">{org.slug}</span></div>
            <div><span className="text-zinc-400">Email master:</span> {org.masterEmail}</div>
            <div><span className="text-zinc-400">Creada:</span> {new Date(org.createdAt).toLocaleDateString("es")}</div>
          </div>
        </section>

        {/* Métricas */}
        <section className="bg-zinc-900 rounded-xl border border-zinc-800 p-5">
          <h2 className="font-semibold text-zinc-200 mb-3">Métricas</h2>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold">{org.metrics.totalClients}</p>
              <p className="text-xs text-zinc-400 mt-1">Clientes</p>
            </div>
            <div>
              <p className="text-2xl font-bold">{org.metrics.totalInvoices}</p>
              <p className="text-xs text-zinc-400 mt-1">Facturas</p>
            </div>
            <div>
              <p className="text-2xl font-bold">{org.metrics.totalUsers}</p>
              <p className="text-xs text-zinc-400 mt-1">Usuarios</p>
            </div>
          </div>
        </section>

        {/* Acciones */}
        <section className="bg-zinc-900 rounded-xl border border-zinc-800 p-5 space-y-3">
          <h2 className="font-semibold text-zinc-200 mb-1">Acciones</h2>
          <div className="flex flex-col gap-2">
            <button
              onClick={handleToggleActive}
              className="text-left px-4 py-2 rounded-lg border border-zinc-700 text-sm hover:bg-zinc-800 transition"
            >
              {org.isActive ? "⏸ Desactivar organización" : "▶ Activar organización"}
            </button>
            <button
              onClick={handleResetPassword}
              className="text-left px-4 py-2 rounded-lg border border-zinc-700 text-sm hover:bg-zinc-800 transition"
            >
              🔑 Restablecer contraseña del master
            </button>
            <button
              onClick={handleDelete}
              className="text-left px-4 py-2 rounded-lg border border-red-900 text-red-400 text-sm hover:bg-red-950 transition"
            >
              🗑 Solicitar eliminación (soft delete 30 días)
            </button>
          </div>
        </section>
      </main>
    </div>
  );
}
