import { defineConfig } from 'vite';

// base './' = relative asset URLs, so the same build works at a domain root or under a sub-path
// such as https://example.com/caduceus/ (no rebuild needed).
export default defineConfig({
  base: './',
  build: { target: 'es2022', assetsInlineLimit: 0 },
  test: { environment: 'node', include: ['tests/**/*.test.ts'], testTimeout: 60000 },
} as any);
