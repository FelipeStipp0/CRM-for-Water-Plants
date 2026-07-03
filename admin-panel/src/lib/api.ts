const BASE = process.env.NEXT_PUBLIC_ADMIN_API_URL!;

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("admin_token");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(err.error ?? "Error desconocido");
  }

  return res.json();
}

export const api = {
  login: (username: string, password: string) =>
    request<{ token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  listOrgs: () => request<Org[]>("/orgs"),

  getOrg: (slug: string) => request<OrgDetail>(`/orgs/${slug}`),

  createOrg: (data: { name: string; slug: string; masterEmail: string }) =>
    request("/orgs", { method: "POST", body: JSON.stringify(data) }),

  toggleActive: (slug: string, isActive: boolean) =>
    request(`/orgs/${slug}/active`, {
      method: "PATCH",
      body: JSON.stringify({ isActive }),
    }),

  resetPassword: (slug: string) =>
    request(`/orgs/${slug}/reset-password`, { method: "POST" }),

  requestDelete: (slug: string, adminEmail: string) =>
    request(`/orgs/${slug}`, {
      method: "DELETE",
      body: JSON.stringify({
        adminEmail,
        baseUrl: BASE,
      }),
    }),
};

export interface Org {
  _id: string;
  name: string;
  slug: string;
  masterEmail: string;
  isActive: boolean;
  deletedAt: string | null;
  createdAt: string;
}

export interface OrgDetail extends Org {
  metrics: {
    totalClients: number;
    totalInvoices: number;
    totalUsers: number;
  };
}
