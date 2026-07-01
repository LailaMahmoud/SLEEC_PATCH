// Secrets are provided at deploy time via `wrangler secret put OPENAI_API_KEY`
// and are not declared in wrangler.jsonc, so `wrangler types` does not add them
// to Env. `env` imported from "cloudflare:workers" is typed as `Cloudflare.Env`,
// so we augment that namespace (declaration merging).
declare namespace Cloudflare {
  interface Env {
    OPENAI_API_KEY: string;
    SECRET_KEY: string;
    DATABASE_URL: string;
  }
}
