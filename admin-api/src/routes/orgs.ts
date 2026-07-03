import { Router, Response } from "express";
import { z } from "zod";
import { requireAuth, AdminRequest } from "../middleware/auth";
import {
  createOrg,
  listOrgs,
  getOrg,
  toggleOrgActive,
  requestDeleteOrg,
  confirmDeleteOrg,
} from "../services/org";
import { resetMasterPassword } from "../services/user";
import { getOrgMetrics } from "../services/metrics";

const router = Router();
router.use(requireAuth);

const createOrgSchema = z.object({
  name: z.string().min(2),
  // O slug é o RUC da empresa, normalizado: remove hífen/espaços e tudo que não
  // for [a-z0-9_], em minúsculas (vira nome do banco e usuario Mongo).
  slug: z
    .string()
    .trim()
    .transform((s) => s.replace(/[^a-z0-9_]/gi, "").toLowerCase())
    .pipe(z.string().min(2, "RUC/slug inválido").max(30)),
  masterEmail: z.string().email(),
});

// Listar orgs
router.get("/", async (_req: AdminRequest, res: Response) => {
  const orgs = await listOrgs();
  res.json(orgs);
});

// Detalhe da org com métricas
router.get("/:slug", async (req: AdminRequest, res: Response) => {
  const org = await getOrg(req.params.slug);
  if (!org) { res.status(404).json({ error: "Organización no encontrada" }); return; }

  const metrics = await getOrgMetrics(req.params.slug);
  res.json({ ...org, metrics });
});

// Criar org
router.post("/", async (req: AdminRequest, res: Response) => {
  const parsed = createOrgSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: parsed.error.flatten().fieldErrors });
    return;
  }

  try {
    await createOrg(parsed.data);
    res.status(201).json({ message: "Organización creada. Credenciales enviadas por email." });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Error interno";
    res.status(400).json({ error: msg });
  }
});

// Ativar / desativar
router.patch("/:slug/active", async (req: AdminRequest, res: Response) => {
  const { isActive } = req.body;
  if (typeof isActive !== "boolean") {
    res.status(400).json({ error: "isActive deve ser boolean" });
    return;
  }
  await toggleOrgActive(req.params.slug, isActive);
  res.json({ message: "Estado actualizado" });
});

// Resetar senha do master
router.post("/:slug/reset-password", async (req: AdminRequest, res: Response) => {
  try {
    await resetMasterPassword(req.params.slug);
    res.json({ message: "Nueva contraseña enviada al email del master" });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Error interno";
    res.status(400).json({ error: msg });
  }
});

// Solicitar deleção (envia email de confirmação)
router.delete("/:slug", async (req: AdminRequest, res: Response) => {
  const { adminEmail, baseUrl } = req.body;
  if (!adminEmail || !baseUrl) {
    res.status(400).json({ error: "adminEmail e baseUrl são obrigatórios" });
    return;
  }
  await requestDeleteOrg(req.params.slug, adminEmail, baseUrl);
  res.json({ message: "Email de confirmación enviado" });
});

// Confirmar deleção via token do email
router.post("/:slug/delete/confirm", async (req: AdminRequest, res: Response) => {
  const { token } = req.query;
  if (!token || typeof token !== "string") {
    res.status(400).json({ error: "Token requerido" });
    return;
  }
  try {
    await confirmDeleteOrg(req.params.slug, token);
    res.json({ message: "Organización marcada para eliminación en 30 días" });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Error interno";
    res.status(400).json({ error: msg });
  }
});

export default router;
