import { MongoClient } from "mongodb";
import { getAdminDb, getMongoClient } from "../models/db";
import { Organization } from "../models/types";
import { encrypt } from "../utils/crypto";
import { generateTempPassword, hashPassword } from "../utils/password";
import { sendWelcomeMaster, sendCriticalActionConfirmation } from "./email";
import { randomBytes } from "crypto";
import { config } from "../config";

function buildConnectionString(slug: string, password: string): string {
  // Extrai host da URL admin (sem credenciais)
  const url = new URL(config.MONGODB_ADMIN_URL);
  return `mongodb://${slug}_user:${password}@${url.host}/wmapp_${slug}?authSource=wmapp_${slug}`;
}

export async function createOrg(opts: {
  name: string;
  slug: string;
  masterEmail: string;
}): Promise<{ tempPassword: string }> {
  const db = getAdminDb();
  const mongoClient = getMongoClient();

  // Verifica slug único
  const existing = await db.collection("organizations").findOne({ slug: opts.slug });
  if (existing) throw new Error(`Slug '${opts.slug}' já está em uso`);

  // 1. Cria usuário MongoDB dedicado para a org
  const orgDbPassword = randomBytes(24).toString("hex");
  const orgDb = mongoClient.db(`wmapp_${opts.slug}`);
  await orgDb.command({
    createUser: `${opts.slug}_user`,
    pwd: orgDbPassword,
    roles: [{ role: "readWrite", db: `wmapp_${opts.slug}` }],
  });

  // 2. Cria coleções iniciais e índices
  await orgDb.collection("users").createIndex({ username: 1 }, { unique: true });
  await orgDb.collection("users").createIndex({ email: 1 }, { unique: true });

  // 3. Cria usuário master na org
  const tempPassword = generateTempPassword();
  await orgDb.collection("users").insertOne({
    username: "master",
    email: opts.masterEmail,
    hashed_password: await hashPassword(tempPassword),
    full_name: "Master",
    role: "master",
    is_active: true,
    must_change_password: true,
    scopes: ["*"],
    created_at: new Date(),
  });

  // 4. Salva org no wmapp_admin com connection string criptografada
  const connStr = buildConnectionString(opts.slug, orgDbPassword);
  const org: Organization = {
    name: opts.name,
    slug: opts.slug,
    masterEmail: opts.masterEmail,
    isActive: true,
    connectionString: encrypt(connStr),
    deletedAt: null,
    createdAt: new Date(),
  };
  await db.collection<Organization>("organizations").insertOne(org);

  // 5. Envia email de boas-vindas
  await sendWelcomeMaster({
    to: opts.masterEmail,
    orgName: opts.name,
    username: "master",
    tempPassword,
  });

  return { tempPassword };
}

export async function listOrgs(): Promise<Organization[]> {
  const db = getAdminDb();
  return db
    .collection<Organization>("organizations")
    .find({ deletedAt: null })
    .project({ connectionString: 0 }) // nunca expõe a conn string
    .sort({ createdAt: -1 })
    .toArray() as Promise<Organization[]>;
}

export async function getOrg(slug: string): Promise<Organization | null> {
  const db = getAdminDb();
  return db
    .collection<Organization>("organizations")
    .findOne({ slug }, { projection: { connectionString: 0 } });
}

export async function toggleOrgActive(slug: string, isActive: boolean): Promise<void> {
  const db = getAdminDb();
  await db.collection("organizations").updateOne(
    { slug },
    { $set: { isActive, updatedAt: new Date() } }
  );
}

export async function requestDeleteOrg(slug: string, adminEmail: string, baseUrl: string): Promise<void> {
  const db = getAdminDb();
  const org = await db.collection<Organization>("organizations").findOne({ slug });
  if (!org) throw new Error("Org não encontrada");

  const token = randomBytes(32).toString("hex");
  await db.collection("organizations").updateOne(
    { slug },
    { $set: { deleteConfirmToken: token, updatedAt: new Date() } }
  );

  await sendCriticalActionConfirmation({
    to: adminEmail,
    action: `Eliminar organización "${org.name}"`,
    orgName: org.name,
    confirmUrl: `${baseUrl}/orgs/${slug}/delete/confirm?token=${token}`,
  });
}

export async function confirmDeleteOrg(slug: string, token: string): Promise<void> {
  const db = getAdminDb();
  const org = await db.collection<Organization>("organizations").findOne({ slug });
  if (!org) throw new Error("Org não encontrada");
  if (org.deleteConfirmToken !== token) throw new Error("Token inválido");

  // Soft delete — dados ficam por 30 dias
  await db.collection("organizations").updateOne(
    { slug },
    {
      $set: {
        deletedAt: new Date(),
        isActive: false,
        deleteConfirmToken: null,
        updatedAt: new Date(),
      },
    }
  );
}

export async function purgeExpiredOrgs(): Promise<void> {
  // Chamado por cron job diário — remove orgs com soft delete > 30 dias
  const db = getAdminDb();
  const mongoClient = getMongoClient();
  const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000);

  const expired = await db
    .collection<Organization>("organizations")
    .find({ deletedAt: { $lte: cutoff } })
    .toArray();

  for (const org of expired) {
    // Remove database da org
    await mongoClient.db(`wmapp_${org.slug}`).dropDatabase();
    // Remove usuário MongoDB da org
    try {
      await mongoClient.db(`wmapp_${org.slug}`).command({
        dropUser: `${org.slug}_user`,
      });
    } catch {
      // Usuário pode já não existir
    }
    // Remove do admin
    await db.collection("organizations").deleteOne({ slug: org.slug });
  }
}
