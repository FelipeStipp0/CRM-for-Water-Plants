import { createCipheriv, createDecipheriv, randomBytes } from "crypto";
import { config } from "../config";

const ALGORITHM = "aes-256-cbc";
const KEY = Buffer.from(config.ENCRYPTION_KEY, "hex");

export function encrypt(text: string): string {
  const iv = randomBytes(16);
  const cipher = createCipheriv(ALGORITHM, KEY, iv);
  const encrypted = Buffer.concat([cipher.update(text, "utf8"), cipher.final()]);
  return `${iv.toString("hex")}:${encrypted.toString("hex")}`;
}

export function decrypt(encrypted: string): string {
  const [ivHex, dataHex] = encrypted.split(":");
  const iv = Buffer.from(ivHex, "hex");
  const data = Buffer.from(dataHex, "hex");
  const decipher = createDecipheriv(ALGORITHM, KEY, iv);
  return Buffer.concat([decipher.update(data), decipher.final()]).toString("utf8");
}
