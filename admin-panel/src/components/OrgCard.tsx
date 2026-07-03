"use client";

import { useRouter } from "next/navigation";
import { Org } from "@/lib/api";

interface Props {
  org: Org;
  onRefresh: () => void;
}

export function OrgCard({ org }: Props) {
  const router = useRouter();

  return (
    <div
      onClick={() => router.push(`/orgs/${org.slug}`)}
      className="bg-zinc-900 border border-zinc-800 rounded-xl px-5 py-4 flex items-center justify-between cursor-pointer hover:border-zinc-600 transition"
    >
      <div className="space-y-0.5">
        <p className="font-medium">{org.name}</p>
        <p className="text-sm text-zinc-400 font-mono">{org.slug}</p>
        <p className="text-xs text-zinc-500">{org.masterEmail}</p>
      </div>

      <div className="flex items-center gap-3">
        <span className={`text-xs px-2 py-0.5 rounded-full ${
          org.isActive ? "bg-green-900 text-green-300" : "bg-red-900 text-red-300"
        }`}>
          {org.isActive ? "Activa" : "Inactiva"}
        </span>
        <span className="text-zinc-600 text-sm">→</span>
      </div>
    </div>
  );
}
