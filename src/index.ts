import { Container, getRandom } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

/**
 * Durable Object that manages a SLEEC-PATCH container instance.
 *
 * The Flask app inside the container listens on 8080 (see Dockerfile gunicorn
 * bind). `sleepAfter` keeps an instance warm between requests to avoid cold
 * starts during a working session.
 */
export class SleecPatchContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "15m";

  // Forward secrets (set via `wrangler secret put ...`) into the container
  // process as host environment variables. Secrets are auto-added to `env`, so
  // they do not need to be declared in wrangler.jsonc.
  envVars = {
    OPENAI_API_KEY: env.OPENAI_API_KEY,
    SECRET_KEY: env.SECRET_KEY,
  };

  override onStart() {
    console.log("SLEEC-PATCH container started");
  }
}

export default {
  /**
   * Stateless app: every request is independent, so we load-balance across a
   * small pool of warm instances rather than pinning to one.
   */
  async fetch(request: Request): Promise<Response> {
    const container = await getRandom(env.SLEEC_PATCH_CONTAINER, 3);
    return container.fetch(request);
  },
};
