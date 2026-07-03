import { MongoClient, Db } from "mongodb";
import { config } from "../config";

let client: MongoClient;
let db: Db;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function connectAdmin(retries = 10, delayMs = 3000): Promise<void> {
  // A rede privada do Railway (*.railway.internal) pode não resolver nos
  // primeiros instantes após o boot; conectar com retry evita crash loop.
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      client = new MongoClient(config.MONGODB_ADMIN_URL);
      await client.connect();
      db = client.db("wmapp_admin");
      console.log("[admin-api] conectado ao wmapp_admin");
      return;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      console.error(`[admin-api] falha ao conectar (tentativa ${attempt}/${retries}): ${msg}`);
      try { await client?.close(); } catch { /* ignore */ }
      if (attempt === retries) throw e;
      await sleep(delayMs);
    }
  }
}

export function getAdminDb(): Db {
  if (!db) throw new Error("DB não inicializado");
  return db;
}

export function getMongoClient(): MongoClient {
  if (!client) throw new Error("Client não inicializado");
  return client;
}
