import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// En développement, /api, /ws et /video sont relayés vers nginx (stack Docker du PC serveur).
// VITE_API_TARGET permet de viser une autre machine, ex. https://192.168.137.1
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const target = env.VITE_API_TARGET || 'https://localhost';
  const proxy = { target, changeOrigin: true, secure: false }; // CA locale : certificat non reconnu par Node
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': proxy,
        '/video': proxy,
        '/ws': { ...proxy, ws: true },
      },
    },
    build: { outDir: 'dist', sourcemap: false },
  };
});
