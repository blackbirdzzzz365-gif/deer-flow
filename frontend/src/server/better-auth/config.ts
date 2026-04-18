import { betterAuth } from "better-auth";

import { env } from "@/env";

export const auth = betterAuth({
  baseURL: env.BETTER_AUTH_BASE_URL,
  emailAndPassword: {
    enabled: true,
  },
});

export type Session = typeof auth.$Infer.Session;
