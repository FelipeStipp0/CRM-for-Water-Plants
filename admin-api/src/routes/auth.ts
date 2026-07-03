import { Router, Request, Response } from "express";
import jwt, { SignOptions } from "jsonwebtoken";
import { z } from "zod";
import { getAdminDb } from "../models/db";
import { SuperAdmin } from "../models/types";
import { verifyPassword } from "../utils/password";
import { config } from "../config";

const router = Router();

const loginSchema = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
});

router.post("/login", async (req: Request, res: Response) => {
  const parsed = loginSchema.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "Datos inválidos" });
    return;
  }

  const db = getAdminDb();
  const admin = await db
    .collection<SuperAdmin>("admins")
    .findOne({ username: parsed.data.username });

  if (!admin || !(await verifyPassword(parsed.data.password, admin.hashedPassword))) {
    res.status(401).json({ error: "Credenciales inválidas" });
    return;
  }

  const signOptions: SignOptions = { expiresIn: config.JWT_EXPIRES_IN as SignOptions["expiresIn"] };
  const token = jwt.sign(
    { sub: admin._id!.toString() },
    config.JWT_SECRET,
    signOptions
  );

  res.json({ token });
});

export default router;
