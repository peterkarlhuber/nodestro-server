#!/usr/bin/env bash
# The vulnerability scan must fail on a known vulnerable package: an image derived from IMAGE that pins an old
# urllib3 in its pip freeze and carries it in site-packages (both scanners see it), and pass again without it.
#   scripts/test_scan_vulnerabilities.sh IMAGE
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
image="${1:?usage: test_scan_vulnerabilities.sh IMAGE}"
work="$(mktemp -d)"
trap 'rm -rf "$work"; docker image rm -f nodestro-scan-test:vulnerable >/dev/null 2>&1 || true' EXIT
# urllib3 1.26.4 has published advisories with fixed versions (for example GHSA-v845-jxx5-vc9f, fixed in 1.26.18).
cat > "$work/Dockerfile" <<DOCKERFILE
FROM $image
USER 0
RUN set -eu; site="\$(echo /opt/nodestro/venv/lib/python3.*/site-packages)"; \
    mkdir -p "\$site/urllib3-1.26.4.dist-info"; \
    printf 'Metadata-Version: 2.1\nName: urllib3\nVersion: 1.26.4\n' > "\$site/urllib3-1.26.4.dist-info/METADATA"; \
    : > "\$site/urllib3-1.26.4.dist-info/RECORD"; \
    grep -v '^urllib3==' /opt/nodestro/pinned.txt > /tmp/pinned.txt; echo 'urllib3==1.26.4' >> /tmp/pinned.txt; \
    mv /tmp/pinned.txt /opt/nodestro/pinned.txt
USER 10001:10001
DOCKERFILE
docker build -q -t nodestro-scan-test:vulnerable "$work" >/dev/null
if "$root/scripts/scan-vulnerabilities.sh" nodestro-scan-test:vulnerable "$work/report" > "$work/out.txt" 2>&1; then
  cat "$work/out.txt"
  echo "FAIL: the scan passed an image with a known vulnerable urllib3" >&2
  exit 1
fi
grep -q '"name": "urllib3"' "$work/report/pip-audit.json" || { cat "$work/out.txt"; echo "FAIL: pip-audit did not report urllib3" >&2; exit 1; }
grep -Eq '^GHSA-[^ ]+ urllib3 1\.26\.4 -> |^CVE-[^ ]+ urllib3 1\.26\.4 -> ' "$work/out.txt" \
  || { cat "$work/out.txt"; echo "FAIL: trivy did not report a fixable urllib3 finding" >&2; exit 1; }
echo "ok: the scan fails on a known vulnerable package (pip-audit and trivy)"
