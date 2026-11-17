FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_RELEASE_VERSION=local
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_RELEASE_VERSION=${NEXT_PUBLIC_RELEASE_VERSION}
COPY package.json tsconfig.json next.config.mjs next-env.d.ts postcss.config.mjs tailwind.config.ts ./
COPY pnpm-lock.yaml ./
COPY src src
RUN pnpm install --frozen-lockfile && pnpm build
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
EXPOSE 3000
ENTRYPOINT ["tini", "--"]
CMD ["node", "server.js"]
