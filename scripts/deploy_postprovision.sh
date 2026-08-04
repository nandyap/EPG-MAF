#!/usr/bin/env sh
# POSIX twin of deploy_postprovision.ps1.
set -eu
echo "== EGP MAF post-provision =="

BACKEND_FQDN=$(azd env get-value BACKENDFQDN 2>/dev/null || true)
FRONTEND_FQDN=$(azd env get-value FRONTENDFQDN 2>/dev/null || true)

if [ -n "${BACKEND_FQDN:-}" ]; then
  echo "Backend FQDN:  $BACKEND_FQDN"
  curl -fsS --max-time 15 "https://$BACKEND_FQDN/health" \
    && echo "  /health OK" \
    || echo "  /health probe failed"
else
  echo "No BACKENDFQDN in azd env — provisioning outputs missing?"
fi

if [ -n "${FRONTEND_FQDN:-}" ]; then
  echo "Frontend FQDN: $FRONTEND_FQDN"
fi

echo "Done. See docs/deployment.md for full verification."
