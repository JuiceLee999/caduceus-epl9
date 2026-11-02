# Caduceus look-pack editor: static site. Build: docker build -t caduceus-looks webapp/
# Stage 1 builds with Node; stage 2 is plain nginx:alpine serving the files as a non-root user on port 8080.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
# the same build at / and /caduceus/ (see nginx.conf)
COPY --from=build /app/dist /usr/share/nginx/html
COPY --from=build /app/dist /usr/share/nginx/html/caduceus
RUN chown -R nginx:nginx /usr/share/nginx/html && nginx -t
USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
