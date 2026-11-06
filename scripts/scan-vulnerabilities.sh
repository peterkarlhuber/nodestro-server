#!/usr/bin/env bash
# Vulnerability scan of a built image (server or the `local` target): its Python packages and its operating system
# packages and binaries.
#
#   scripts/scan-vulnerabilities.sh IMAGE [REPORT_DIR]
#
# 1. Python: the image's own pip freeze (/opt/nodestro/pinned.txt) without the Nodestro components (installed from
#    git at pinned commits, not on PyPI), audited with pip-audit against the PyPA advisory database (OSV). Any known
#    vulnerability fails the scan.
# 2. Operating system packages and binaries (Debian packages, the docker CLI, the Python packages once more): Trivy,
#    the image in scripts/scanner/Dockerfile (pinned by digest), on the saved image. A HIGH or CRITICAL finding that
#    has a fixed version fails the scan; findings without a fix are listed in the report only (they cannot be acted on
#    until Debian ships a fix; the next base image refresh picks it up).
#
# REPORT_DIR (default: a temporary directory) receives pip-audit.json, trivy.json and trivy.txt (every severity,
# fixed or not), so a release reviewer can read the full state. Needs Docker and pip-audit (CI installs a pinned
# version). Behind a TLS-inspecting proxy, NODESTRO_EXTRA_CA_FILE names its certificate bundle; the scanner then uses
# the host network, so HTTPS_PROXY on 127.0.0.1 works. NODESTRO_SCAN_SEVERITY changes the failing severities.
# Accepted findings are listed with a reason in scripts/vulnerability-allow.txt (one ID per line, `# reason`).
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
image="${1:?usage: scan-vulnerabilities.sh IMAGE [REPORT_DIR]}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
report="${2:-$work/report}"
mkdir -p "$report"
severity="${NODESTRO_SCAN_SEVERITY:-HIGH,CRITICAL}"
scanner="$(sed -n 's/^FROM \(\S*@sha256:[0-9a-f]\{64\}\)$/\1/p' "$root/scripts/scanner/Dockerfile")"
[ -n "$scanner" ] || { echo "scripts/scanner/Dockerfile names no scanner image by digest" >&2; exit 1; }
allow="$root/scripts/vulnerability-allow.txt"
ignored=()
if [ -f "$allow" ]; then
  while read -r id _; do
    case "$id" in ""|"#"*) continue ;; esac
    ignored+=("$id")
  done < "$allow"
fi
status=0

# ---- 1. Python packages (pip-audit) -------------------------------------------------------------------------------
docker run --rm --network none --entrypoint cat "$image" /opt/nodestro/pinned.txt > "$work/pinned.txt"
grep -E '^[A-Za-z0-9][A-Za-z0-9._-]*==[^ ]+$' "$work/pinned.txt" > "$work/pypi.txt" || true
skipped="$(grep -cvE '^[A-Za-z0-9][A-Za-z0-9._-]*==[^ ]+$' "$work/pinned.txt" || true)"
[ -s "$work/pypi.txt" ] || { echo "no PyPI packages in the image's pinned.txt" >&2; exit 1; }
echo "pip-audit: $(wc -l < "$work/pypi.txt") packages from PyPI ($skipped pinned components from git are not on PyPI)"
audit_args=(--requirement "$work/pypi.txt" --no-deps --disable-pip --strict --progress-spinner off)
for id in "${ignored[@]}"; do audit_args+=(--ignore-vuln "$id"); done
if ! pip-audit "${audit_args[@]}" --format json --output "$report/pip-audit.json"; then
  pip-audit "${audit_args[@]}" --format columns || true
  echo "::error::pip-audit found known vulnerabilities in the image's Python packages (or could not audit them)" >&2
  status=1
fi

# ---- 2. Operating system packages and binaries (Trivy) ----------------------------------------------------------
docker save -o "$work/image.tar" "$image"
run=(docker run --rm --quiet -v "$work:/scan" -v "nodestro-trivy-cache:/root/.cache/trivy")
if [ -n "${NODESTRO_EXTRA_CA_FILE:-}" ]; then
  run+=(--network host -v "$NODESTRO_EXTRA_CA_FILE:/etc/ssl/certs/extra-ca.pem:ro" -e SSL_CERT_FILE=/etc/ssl/certs/extra-ca.pem)
  for name in HTTPS_PROXY NO_PROXY; do
    if [ -n "${!name:-}" ]; then run+=(-e "$name=${!name}"); fi
  done
fi
: > "$work/trivyignore"
for id in "${ignored[@]}"; do echo "$id" >> "$work/trivyignore"; done
trivy=(image --input /scan/image.tar --scanners vuln --pkg-types "os,library" --ignorefile /scan/trivyignore --quiet)
"${run[@]}" "$scanner" "${trivy[@]}" --format json --output /scan/trivy.json
"${run[@]}" "$scanner" "${trivy[@]}" --skip-db-update --format table --output /scan/trivy.txt
cp "$work/trivy.json" "$work/trivy.txt" "$report/"
if ! python3 -I - "$work/trivy.json" "$severity" <<'PY'
import collections, json, sys
data = json.load(open(sys.argv[1]))
failing = set(sys.argv[2].split(","))
counts, fixable = collections.Counter(), []
for result in data.get("Results") or []:
    for vuln in result.get("Vulnerabilities") or []:
        fixed = bool(vuln.get("FixedVersion"))
        counts[(result.get("Type", "?"), vuln.get("Severity", "UNKNOWN"), "fix" if fixed else "no fix")] += 1
        if fixed and vuln.get("Severity") in failing:
            fixable.append(f'{vuln["VulnerabilityID"]} {vuln["PkgName"]} {vuln.get("InstalledVersion")} -> {vuln["FixedVersion"]}')
for (kind, severity, fix), count in sorted(counts.items()):
    print(f"trivy: {count:4d} {severity:8s} {fix:6s} ({kind})")
if fixable:
    print("\n".join(sorted(set(fixable))))
    print(f"::error::{len(set(fixable))} {'/'.join(sorted(failing))} findings have a fixed version: refresh the base image or the package")
    sys.exit(1)
PY
then
  status=1
fi
echo "reports in $report"
exit "$status"
