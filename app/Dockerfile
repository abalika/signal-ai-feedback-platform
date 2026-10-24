FROM node:22-alpine AS build

WORKDIR /workspace/app
COPY app/package.json app/package-lock.json ./
RUN npm ci
COPY app/ ./
COPY examples/ /workspace/examples/
COPY docs/reports/ /workspace/docs/reports/
RUN npm run build

FROM nginx:1.27-alpine
COPY app/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/app/dist /usr/share/nginx/html
EXPOSE 80
