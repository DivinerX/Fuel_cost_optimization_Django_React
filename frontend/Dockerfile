# Build stage
FROM node:18-alpine AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci

# Copy source code
COPY . .

# Accept build argument for API URL
ARG REACT_APP_API_URL
ENV REACT_APP_API_URL=$REACT_APP_API_URL

# Build the app
RUN npm run build

# Production stage
FROM node:18-alpine

WORKDIR /app

# Install serve globally to serve the static files
RUN npm install -g serve

# Copy entrypoint script
COPY docker-entrypoint.js /app/docker-entrypoint.js
RUN chmod +x /app/docker-entrypoint.js

# Copy built files from builder stage
COPY --from=builder /app/build ./build

# Expose port 8080
EXPOSE 8080

# Use entrypoint script that injects API URL at runtime
ENTRYPOINT ["node", "/app/docker-entrypoint.js"]

