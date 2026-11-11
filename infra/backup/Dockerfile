# Servicio de respaldos (REQ-RNF-08): misma versión mayor de PostgreSQL que la BD.
FROM postgres:16-alpine
RUN apk add --no-cache tzdata
COPY backup.sh restore.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD sh -c 'test -f /tmp/backup-alive && [ $(( $(date +%s) - $(cat /tmp/backup-alive) )) -lt 180 ]'
ENTRYPOINT []
CMD ["backup.sh", "daemon"]
