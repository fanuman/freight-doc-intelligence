# The web image: the Next.js app, built once and served by a small Node server.
#   build:  docker build -t freightlens-web --build-arg API_URL=http://api:8000 web
#
# Three stages. Only the last one becomes the image; the first two are scratch space that is thrown away,
# so the toolchain and the development libraries never reach the final image.

# Stage 1: install the libraries (cached until package.json or package-lock.json changes)
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# Stage 2: build the app
FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Where the /api proxy sends requests. It is read at BUILD time and baked into the build, so changing it
# later means building again. On AWS the API shares the task with this container, so localhost is right.
ARG API_URL=http://127.0.0.1:8000
ENV API_URL=$API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Stage 3: the image that runs
FROM node:20-alpine AS run
WORKDIR /app
# HOSTNAME=0.0.0.0: listen for connections from outside the container (the default would only listen inside).
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
# The sign-in page needs no login and no API, so it is a good "is the web server alive?" check.
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/login || exit 1
CMD ["node", "server.js"]
