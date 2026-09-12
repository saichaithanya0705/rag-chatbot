import { fileURLToPath, URL } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export function validateProductionApiBaseUrl(mode: string, rawValue: string | undefined) {
  if (mode !== "production") {
    return;
  }

  const value = rawValue?.trim();
  if (!value) {
    throw new Error("VITE_API_BASE_URL is required for production builds.");
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new Error("VITE_API_BASE_URL must be a valid absolute HTTP(S) URL.");
  }

  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("VITE_API_BASE_URL must use HTTP or HTTPS.");
  }

  if (["localhost", "127.0.0.1", "::1"].includes(url.hostname)) {
    throw new Error("VITE_API_BASE_URL must not target a loopback host in production.");
  }
}

export default defineConfig(({ mode }) => {
  const fileEnvironment = loadEnv(mode, process.cwd(), "");
  validateProductionApiBaseUrl(
    mode,
    process.env.VITE_API_BASE_URL ?? fileEnvironment.VITE_API_BASE_URL,
  );

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
    },
  };
});
