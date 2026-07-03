import "dotenv/config";
import express from "express";
import cors from "cors";
import { config } from "./config";
import { connectAdmin } from "./models/db";
import { purgeExpiredOrgs } from "./services/org";
import authRouter from "./routes/auth";
import orgsRouter from "./routes/orgs";

const app = express();

app.use(cors({ origin: process.env.ADMIN_PANEL_URL ?? "*" }));
app.use(express.json());

// Rotas
app.use("/auth", authRouter);
app.use("/orgs", orgsRouter);

// Health check — não expõe informações
app.get("/health", (_req, res) => res.json({ ok: true }));

// Cron diário: limpa orgs com soft delete > 30 dias
function schedulePurge() {
  const now = new Date();
  const next = new Date();
  next.setHours(3, 0, 0, 0); // 03:00 todo dia
  if (next <= now) next.setDate(next.getDate() + 1);

  setTimeout(async () => {
    try { await purgeExpiredOrgs(); } catch (e) { console.error("[purge] erro:", e); }
    schedulePurge();
  }, next.getTime() - now.getTime());
}

async function main() {
  await connectAdmin();
  schedulePurge();
  app.listen(config.PORT, () => {
    console.log(`[admin-api] rodando na porta ${config.PORT}`);
  });
}

main().catch((e) => { console.error(e); process.exit(1); });
