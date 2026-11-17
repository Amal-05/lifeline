FROM node:26.13.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/package.json
COPY packages/protocol/ts/package.json packages/protocol/ts/package.json
RUN npm ci
COPY apps/web apps/web
COPY packages/protocol/ts packages/protocol/ts
RUN npm run build --workspace @lifeline/web
FROM nginx:1.27.3-alpine
COPY --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 80
