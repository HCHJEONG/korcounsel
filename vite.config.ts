import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
    fs: {
      // Preserve Vite 8.2.2 defaults; private workspace data is served by FastAPI.
      deny: ['.env', '.env.*', '*.{crt,pem,key,p12,pfx,cer,der}', '.npmrc', '.yarnrc.yml', '**/.git/**',
        '**/data/**', '**/backend/**', '**/.fordeploy/**', '**/test-results/**', '**/playwright-report/**'],
    },
    watch: { ignored: ['**/data/**', '**/backend/**', '**/.fordeploy/**', '**/test-results/**', '**/playwright-report/**'] } },
  preview: { host: '127.0.0.1', port: 4173, strictPort: true },
})
