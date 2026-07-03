import "dotenv/config";
import { MongoClient } from "mongodb";
import bcrypt from "bcryptjs";

async function main() {
  const url = process.env.MONGODB_ADMIN_URL!;
  const client = new MongoClient(url);
  await client.connect();
  const db = client.db("wmapp_admin");
  const existing = await db.collection("admins").findOne({ username: "admin" });
  if (existing) {
    console.log("Superadmin ja existe");
    await client.close();
    return;
  }
  await db.collection("admins").insertOne({
    username: "admin",
    hashedPassword: await bcrypt.hash("Admin@123", 12),
    createdAt: new Date(),
  });
  console.log("Superadmin criado — usuario: admin  senha: Admin@123");
  await client.close();
}

main().catch(console.error);
