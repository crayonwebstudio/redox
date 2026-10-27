# Build stage
FROM node:22-alpine AS build
# package.json prebuild runs scripts/build.py (stdlib only); the guard inside
# skips cleanly when demo sources are absent, but python3 itself must exist.
RUN apk add --no-cache python3
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
