/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'true' — демо-данные без бэкенда, 'false' — настоящий API */
  readonly VITE_USE_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
