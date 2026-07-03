import { getAdminDb, getMongoClient } from "../models/db";
import { Organization } from "../models/types";
import { decrypt } from "../utils/crypto";
import { generateTempPassword, hashPassword } from "../utils/password";
import { sendPasswordReset } from "./email";

export async function resetMasterPassword(slug: string): Promise<void> {
  const adminDb = getAdminDb();
  const org = await adminDb.collection<Organization>("organizations").findOne({ slug });
  if (!org) throw new Error("Org não encontrada");

  // Conecta no banco da org com a connection string dela
  const connStr = decrypt(org.connectionString);
  const orgClient = getMongoClient();
  const orgDb = orgClient.db(`wmapp_${slug}`);

  const master = await orgDb.collection("users").findOne({ role: "master" });
  if (!master) throw new Error("Usuário master não encontrado");

  const tempPassword = generateTempPassword();
  await orgDb.collection("users").updateOne(
    { role: "master" },
    {
      $set: {
        hashedPassword: await hashPassword(tempPassword),
        mustChangePassword: true,
        updatedAt: new Date(),
      },
    }
  );

  await sendPasswordReset({
    to: org.masterEmail,
    orgName: org.name,
    username: master.username as string,
    tempPassword,
  });
}
