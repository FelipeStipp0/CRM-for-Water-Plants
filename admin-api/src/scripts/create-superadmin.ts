/**
 * Roda uma vez no setup inicial para criar o superadmin.
 * Uso: MONGODB_ADMIN_URL=... ENCRYPTION_KEY=... tsx src/scripts/create-superadmin.ts
 */

import "dotenv/config";
import { MongoClient } from "mongodb";
import bcrypt from "bcryptjs";
import * as readline from "readline";

async function prompt(question: string): Promise<string> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(question, (ans) => { rl.close(); resolve(ans); }));
}

async function main() {
  const url = process.env.MONGODB_ADMIN_URL;
  if (!url) { console.error("MONGODB_ADMIN_URL não definida"); process.exit(1); }

  const username = await prompt("Username do superadmin: ");
  const password = await prompt("Senha do superadmin: ");

  const client = new MongoClient(url);
  await client.connect();
  const db = client.db("wmapp_admin");

  const existing = await db.collection("admins").findOne({ username });
  if (existing) { console.error("Superadmin já existe"); await client.close(); process.exit(1); }

  await db.collection("admins").insertOne({
    username,
    hashedPassword: await bcrypt.hash(password, 12),
    createdAt: new Date(),
  });

  console.log(`Superadmin '${username}' criado com sucesso.`);
  await client.close();
}

main().catch(console.error);
