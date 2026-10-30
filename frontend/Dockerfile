# Шаг 1: собираем React-приложение в статические файлы
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
# Когда в репозитории появится package-lock.json — заменить на `npm ci`
RUN npm install
COPY . .
ARG VITE_USE_MOCK=false
ENV VITE_USE_MOCK=$VITE_USE_MOCK
RUN npm run build

# Шаг 2: nginx отдаёт фронт и пересылает /api на бэкенд (один адрес → cookie работают без CORS)
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
