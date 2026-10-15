// Stand-in for the render image in the updater end-to-end test.
const http = require("http");

const version = process.env.FAKE_VERSION || "0.0.0";

http
  .createServer((req, res) => {
    const ok = req.url === "/health";
    res.writeHead(ok ? 200 : 404, { "Content-Type": "application/json" });
    res.end(JSON.stringify(ok ? { ok: true, version } : { ok: false }));
  })
  .listen(3000, "0.0.0.0", () => console.log(`fake render ${version} on :3000`));

process.on("SIGTERM", () => process.exit(0));
