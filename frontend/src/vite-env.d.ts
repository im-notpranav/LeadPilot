/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** wss://host of the backend when the dashboard is served from another domain (e.g. Vercel + Render). */
  readonly VITE_BACKEND_WS_URL?: string;
}
