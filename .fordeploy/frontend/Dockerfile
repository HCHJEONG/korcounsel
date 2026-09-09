FROM node:24.16.0-bookworm-slim AS build
WORKDIR /app
RUN npm install --global pnpm@11.23.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN pnpm build
FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# .fordeploy is excluded from build context; mount config through Compose.
