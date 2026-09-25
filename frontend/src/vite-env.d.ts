/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "true" enables the RaceWise hand-off seam. Off by default: contract not finalized. */
  readonly VITE_RACEWISE_ENABLED?: string;
}
