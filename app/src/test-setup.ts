import { afterEach } from "vitest"

import { resetApiCache } from "@/api/use-api"

// Answers remembered by useApi must not leak from one test into the next.
afterEach(() => resetApiCache())
