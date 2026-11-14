// Vercel Cron target: pings the AWS backend so it stays warm and the deployment shows activity.
module.exports = async (req, res) => {
  const base = process.env.BACKEND_URL || "https://kcjwxwjdaefxakn7l6nrtntqnu0ronmo.lambda-url.ap-south-1.on.aws";
  try { const r = await fetch(base + "/api/health"); res.status(200).json({ ok: r.ok, status: r.status }); }
  catch (e) { res.status(200).json({ ok: false, error: String(e) }); }
};
