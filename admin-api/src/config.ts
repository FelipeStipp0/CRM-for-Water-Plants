import { z } from "zod";

const envSchema = z.object({
  MONGODB_ADMIN_URL: z.string().min(1),
  ENCRYPTION_KEY: z.string().length(64, "ENCRYPTION_KEY deve ter 64 caracteres hex (AES-256)"),
  JWT_SECRET: z.string().min(32),
  JWT_EXPIRES_IN: z.string().default("8h"),
  FORWARD_EMAIL_API_KEY: z.string().min(1),
  // Remetente dos emails, ex.: "Saneo <no-reply@seu-dominio.com>" (domínio verificado).
  EMAIL_FROM: z.string().min(1),
  // URL pública do logo usado no cabeçalho dos emails.
  EMAIL_LOGO_URL: z.string().url(),
  PORT: z.coerce.number().default(3001),
});

const parsed = envSchema.safeParse(process.env);
if (!parsed.success) {
  console.error("Variáveis de ambiente inválidas:");
  console.error(parsed.error.flatten().fieldErrors);
  process.exit(1);
}

export const config = parsed.data;
