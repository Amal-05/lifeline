FROM node:26.13.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/protocol/ts/package.json packages/protocol/ts/package.json
# npm 10 on Windows can omit foreign-platform optional packages from lock v3.
# npm install honors the lockfile and materializes the Linux optional packages here.
RUN npm install --include=optional --no-audit --no-fund
COPY apps/web apps/web
COPY packages/protocol/ts packages/protocol/ts
RUN npm run build --workspace @lifeline/web
FROM nginx:1.27.3-alpine
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
