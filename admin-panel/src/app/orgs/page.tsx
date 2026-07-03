"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, Org } from "@/lib/api";
import { CreateOrgDialog } from "@/components/CreateOrgDialog";
import { OrgCard } from "@/components/OrgCard";

export default function OrgsPage() {
  const router = useRouter();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    try {
      const data = await api.listOrgs();
      setOrgs(data);
    } catch (err: unknown) {
      if (err instanceof Error && err.message.includes("Token")) {
        router.push("/login");
      } else {
        setError("Error al cargar organizaciones");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function handleLogout() {
    localStorage.removeItem("admin_token");
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-800 px-6 py-4 flex items-center justify-between">
        <h1 className="font-bold text-lg">Saneo — Admin</h1>
        <div className="flex items-center gap-3">
          <CreateOrgDialog onCreated={load} />
          <button
            onClick={handleLogout}
            className="text-sm text-zinc-400 hover:text-zinc-200 transition"
          >
            Salir
          </button>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold">Organizaciones</h2>
          <span className="text-zinc-400 text-sm">{orgs.length} registradas</span>
        </div>

        {loading && <p className="text-zinc-400">Cargando...</p>}
        {error && <p className="text-red-400">{error}</p>}

        <div className="grid gap-3">
          {orgs.map((org) => (
            <OrgCard key={org.slug} org={org} onRefresh={load} />
          ))}
        </div>
      </main>
    </div>
  );
}
