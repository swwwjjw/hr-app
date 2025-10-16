#FROM node:alpine as build
#COPY package.json package.json
#WORKDIR /usr/app
#COPY ./ /usr/app
#RUN npm install
#RUN npm run build
#FROM nginx:stable-alpine
#COPY --from=build /dist /usr/share/nginx/html
#COPY --from=build nginx.conf /etc/nginx/conf.d/default.conf
#EXPOSE 8000
#CMD [ "nginx", "-g", "daemon off;" ]
FROM node:18-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npx react-scripts build
FROM nginx:alpine
COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]