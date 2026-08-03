FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install

FROM deps AS build
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup -S vmec && adduser -S vmec -G vmec
COPY --from=build --chown=vmec:vmec /app/.next/standalone ./
COPY --from=build --chown=vmec:vmec /app/.next/static ./.next/static
USER vmec
EXPOSE 3000
CMD ["node", "server.js"]
