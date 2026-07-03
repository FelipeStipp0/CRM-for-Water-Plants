import { config } from "../config";

// Forward Email — API de envio. Auth HTTP Basic: usuário = API key, senha vazia.
// Docs: https://forwardemail.net/email-api
const API_URL = "https://api.forwardemail.net/v1/emails";

// Remetente (domínio verificado) — configurado via env EMAIL_FROM.
const FROM = config.EMAIL_FROM;

// Paleta do app (frontend/components/theme.py) — emails seguem o mesmo padrão.
const C = {
  bg: "#1a1a2e",
  card: "#16213e",
  surface: "#0f3460",
  accent: "#e94560",       // primário (botões/destaques)
  accent2: "#0ea5e9",      // secundário (links/labels)
  textPrimary: "#f8fafc",
  textSecondary: "#94a3b8",
  textMuted: "#64748b",
  border: "#334155",
};

/** Casca HTML com a marca Saneo, no tema escuro do app. */
function layout(opts: { title: string; bodyHtml: string }): string {
  return `<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>Saneo</title>
</head>
<body style="margin:0;padding:0;background:${C.bg};font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${C.bg};padding:32px 12px;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:${C.card};border:1px solid ${C.border};border-radius:16px;overflow:hidden;">
      <tr><td style="background:${C.surface};padding:32px 40px;border-bottom:1px solid ${C.border};">
        <img src="${config.EMAIL_LOGO_URL}" alt="Saneo" width="150" style="display:block;border:0;outline:none;height:auto;">
        <div style="font-size:12px;color:${C.textSecondary};margin-top:10px;letter-spacing:2px;text-transform:uppercase;">Sistema de Saneamiento</div>
      </td></tr>
      <tr><td style="padding:36px 40px 8px 40px;">
        <h1 style="margin:0 0 14px 0;font-size:22px;color:${C.textPrimary};font-weight:700;">${opts.title}</h1>
        ${opts.bodyHtml}
      </td></tr>
      <tr><td style="padding:22px 40px 32px 40px;border-top:1px solid ${C.border};">
        <p style="margin:0;font-size:13px;color:${C.textSecondary};">Atentamente,<br><strong style="color:${C.textPrimary};">Equipo ArqSoftware</strong></p>
      </td></tr>
    </table>
    <div style="font-size:11px;color:${C.textMuted};margin-top:18px;">Saneo · Sistema de gestión para juntas de saneamiento</div>
  </td></tr>
</table>
</body>
</html>`;
}

/** Parágrafo do corpo. */
function p(text: string): string {
  return `<p style="margin:0 0 18px 0;font-size:15px;line-height:1.65;color:${C.textSecondary};">${text}</p>`;
}

/** Nota secundária menor. */
function note(text: string): string {
  return `<p style="margin:0;font-size:13px;line-height:1.6;color:${C.textMuted};">${text}</p>`;
}

/** Card de credenciais (usuário + senha temporal em destaque). */
function credentialsCard(username: string, tempPassword: string): string {
  return `
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:${C.surface};border:1px solid ${C.border};border-radius:12px;margin:6px 0 24px 0;">
    <tr><td style="padding:20px 22px;">
      <div style="font-size:11px;font-weight:700;color:${C.accent2};letter-spacing:1px;text-transform:uppercase;margin-bottom:14px;">Credenciales de acceso</div>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:${C.textPrimary};">
        <tr><td style="padding:7px 0;color:${C.textSecondary};">Usuario</td>
            <td style="padding:7px 0;text-align:right;font-weight:600;color:${C.textPrimary};">${username}</td></tr>
        <tr><td colspan="2" style="border-top:1px solid ${C.border};font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr><td style="padding:7px 0;color:${C.textSecondary};">Contraseña temporal</td>
            <td style="padding:7px 0;text-align:right;">
              <span style="font-family:'Consolas',monospace;background:${C.accent};color:#ffffff;padding:5px 13px;border-radius:6px;font-weight:600;letter-spacing:1px;">${tempPassword}</span>
            </td></tr>
      </table>
    </td></tr>
  </table>`;
}

/** Botão CTA principal. */
function button(href: string, label: string): string {
  return `
  <table role="presentation" cellpadding="0" cellspacing="0" style="margin:4px 0 22px 0;"><tr>
    <td style="border-radius:10px;background:${C.accent};">
      <a href="${href}" target="_blank" style="display:inline-block;padding:13px 30px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px;">${label}</a>
    </td>
  </tr></table>`;
}

async function sendEmail(opts: {
  to: string;
  subject: string;
  html: string;
}): Promise<void> {
  const auth = Buffer.from(`${config.FORWARD_EMAIL_API_KEY}:`).toString("base64");
  const res = await fetch(API_URL, {
    method: "POST",
    headers: {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: FROM,
      to: opts.to,
      subject: opts.subject,
      html: opts.html,
    }),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`Forward Email ${res.status}: ${body}`);
  }
}

export async function sendWelcomeMaster(opts: {
  to: string;
  orgName: string;
  username: string;
  tempPassword: string;
}): Promise<void> {
  await sendEmail({
    to: opts.to,
    subject: `Bienvenido a Saneo — ${opts.orgName}`,
    html: layout({
      title: "¡Bienvenido a Saneo!",
      bodyHtml:
        p(`Su organización <strong style="color:${C.textPrimary};">${opts.orgName}</strong> ha sido registrada exitosamente. Desde el sistema podrá gestionar clientes, lecturas, facturación, cortes y reactivaciones.`) +
        credentialsCard(opts.username, opts.tempPassword) +
        note("Al ingresar por primera vez, el sistema le solicitará cambiar su contraseña."),
    }),
  });
}

export async function sendPasswordReset(opts: {
  to: string;
  orgName: string;
  username: string;
  tempPassword: string;
}): Promise<void> {
  await sendEmail({
    to: opts.to,
    subject: `Restablecimiento de contraseña — ${opts.orgName}`,
    html: layout({
      title: "Restablecimiento de contraseña",
      bodyHtml:
        p(`Se ha generado una nueva contraseña temporal para su cuenta en <strong style="color:${C.textPrimary};">${opts.orgName}</strong>.`) +
        credentialsCard(opts.username, opts.tempPassword) +
        note("Si no solicitó este cambio, comuníquese con nosotros de inmediato."),
    }),
  });
}

export async function sendOperatorInvite(opts: {
  to: string;
  orgName: string;
  username: string;
  tempPassword: string;
  invitedBy: string;
}): Promise<void> {
  await sendEmail({
    to: opts.to,
    subject: `Invitación a Saneo — ${opts.orgName}`,
    html: layout({
      title: "Ha sido invitado a Saneo",
      bodyHtml:
        p(`<strong style="color:${C.textPrimary};">${opts.invitedBy}</strong> le ha invitado a unirse a <strong style="color:${C.textPrimary};">${opts.orgName}</strong>.`) +
        credentialsCard(opts.username, opts.tempPassword) +
        note("Al ingresar por primera vez, el sistema le solicitará cambiar su contraseña."),
    }),
  });
}

export async function sendCriticalActionConfirmation(opts: {
  to: string;
  action: string;
  orgName: string;
  confirmUrl: string;
}): Promise<void> {
  await sendEmail({
    to: opts.to,
    subject: `Confirmación requerida — ${opts.action}`,
    html: layout({
      title: "Confirmación de acción crítica",
      bodyHtml:
        p(`Se ha solicitado la siguiente acción sobre <strong style="color:${C.textPrimary};">${opts.orgName}</strong>:`) +
        p(`<strong style="color:${C.accent};">${opts.action}</strong>`) +
        p("Para confirmar, haga clic en el siguiente botón. El enlace expira en 1 hora.") +
        button(opts.confirmUrl, "Confirmar acción") +
        note("Si no solicitó esta acción, ignórelo."),
    }),
  });
}
