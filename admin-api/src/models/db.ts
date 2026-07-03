import { MongoClient, Db } from "mongodb";
import { config } from "../config";

let client: MongoClient;
let db: Db;

export async function connectAdmin(): Promise<void> {
  client = new MongoClient(config.MONGODB_ADMIN_URL);
  await client.connect();
  db = client.db("wmapp_admin");
  console.log("[admin-api] conectado ao wmapp_admin");
}

export function getAdminDb(): Db {
  if (!db) throw new Error("DB não inicializado");
  return db;
}

export function getMongoClient(): MongoClient {
  if (!client) throw new Error("Client não inicializado");
  return client;
}
