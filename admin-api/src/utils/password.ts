import bcrypt from "bcryptjs";
import { randomBytes } from "crypto";

export function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 12);
}

export function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export function generateTempPassword(): string {
  return randomBytes(6).toString("hex").toUpperCase(); // ex: A3F9B2C1D4E5
}
