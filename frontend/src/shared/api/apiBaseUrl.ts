const DEFAULT_DEVELOPMENT_API_BASE_URL = "http://localhost:8000";

const configuredApiBaseUrl = import.meta.env?.VITE_API_BASE_URL?.trim();

export const API_BASE_URL = (configuredApiBaseUrl || DEFAULT_DEVELOPMENT_API_BASE_URL).replace(
  /\/+$/,
  "",
);
