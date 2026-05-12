FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

ARG VITE_QUESTION_API_BASE
ARG VITE_REVIEW_API_BASE

ENV VITE_QUESTION_API_BASE=$VITE_QUESTION_API_BASE
ENV VITE_REVIEW_API_BASE=$VITE_REVIEW_API_BASE

RUN npm run build


FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80