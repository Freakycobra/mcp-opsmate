# =============================================================================
# mcp-opsmate Web — Multi-stage Dockerfile
# React 18 + Vite → Nginx
# Build context: project root (.)
# =============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Build
# ------------------------------------------------------------------------------
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies (from opsmate-web/)
COPY opsmate-web/package.json ./
RUN npm install --silent

# Copy source from opsmate-web/ and build
COPY opsmate-web/ .
RUN npx vite build

# ------------------------------------------------------------------------------
# Stage 2: Production (nginx)
# ------------------------------------------------------------------------------
FROM nginx:alpine AS runtime

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config (from project root)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built React app from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Create non-root user for nginx
RUN adduser -D -u 1000 -g 1000 opsmate || true

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
