FROM node:22-alpine

ENV PYTHONUNBUFFERED=1 \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false

WORKDIR /app

# Install first so dependency layers cache independently of source changes.
COPY package.json ./
RUN npm install

COPY . .

# TanStack Start SSR app: the Vite dev server is the reliable runtime for demos.
EXPOSE 8080
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "8080"]
