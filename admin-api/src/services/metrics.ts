import { getAdminDb, getMongoClient } from "../models/db";
import { Organization } from "../models/types";
import { decrypt } from "../utils/crypto";

export interface OrgMetrics {
  totalClients: number;
  totalInvoices: number;
  totalUsers: number;
  lastActivity?: Date;
}

export async function getOrgMetrics(slug: string): Promise<OrgMetrics> {
  const adminDb = getAdminDb();
  const org = await adminDb.collection<Organization>("organizations").findOne({ slug });
  if (!org) return { totalClients: 0, totalInvoices: 0, totalUsers: 0 };

  try {
    // Usa o client existente — o usuário admin tem acesso ao wmapp_admin apenas,
    // mas o superadmin_user precisa ter permissão de leitura em wmapp_* para métricas.
    // Se não tiver, retorna zeros sem quebrar.
    const orgDb = getMongoClient().db(`wmapp_${slug}`);
    const [totalClients, totalInvoices, totalUsers] = await Promise.all([
      orgDb.collection("clients").countDocuments(),
      orgDb.collection("invoices").countDocuments(),
      orgDb.collection("users").countDocuments(),
    ]);

    return { totalClients, totalInvoices, totalUsers };
  } catch {
    return { totalClients: 0, totalInvoices: 0, totalUsers: 0 };
  }
}
