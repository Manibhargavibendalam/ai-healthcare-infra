# Non-root by construction: nginx-unprivileged runs master+workers as `nginx`.
# Pinned exact patch (verified on Docker Hub, M3). No secrets, no build args.
FROM nginxinc/nginx-unprivileged:1.31.6-alpine
USER nginx
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
# Fail the build on a bad config, not at 2am.
RUN nginx -t
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
