import { ObjectId } from "mongodb";

export interface Organization {
  _id?: ObjectId;
  name: string;
  slug: string;
  masterEmail: string;
  isActive: boolean;
  // Connection string da org criptografada com AES-256
  connectionString: string;
  deletedAt?: Date | null;       // soft delete — null = ativa
  deleteConfirmToken?: string;   // token de confirmação de deleção por email
  createdAt: Date;
  updatedAt?: Date;
}

export interface SuperAdmin {
  _id?: ObjectId;
  username: string;
  hashedPassword: string;
  createdAt: Date;
}

export interface AuditLog {
  _id?: ObjectId;
  action: string;         // "create_org" | "delete_org" | "reset_password" | etc.
  targetOrgSlug?: string;
  performedAt: Date;
  meta?: Record<string, unknown>;
}
