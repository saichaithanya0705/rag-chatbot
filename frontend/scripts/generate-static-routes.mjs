import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(__dirname, "..");
const distRoot = resolve(frontendRoot, "dist");
const indexHtmlPath = resolve(distRoot, "index.html");
const staticRoutes = ["chat", "pipeline", "knowledge-graph"];

async function main() {
  const indexHtml = await readFile(indexHtmlPath, "utf8");

  await Promise.all(
    staticRoutes.map(async (routePath) => {
      const routeDir = resolve(distRoot, routePath);
      await mkdir(routeDir, { recursive: true });
      await writeFile(resolve(routeDir, "index.html"), indexHtml, "utf8");
    }),
  );

  await writeFile(resolve(distRoot, "404.html"), indexHtml, "utf8");
}

await main();
