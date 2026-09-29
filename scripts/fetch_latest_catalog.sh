#!/usr/bin/env bash
# Download the newest published catalog (release tag "catalog-*") and extract it into DEST.
#
# Shared by catalog.yml (previous state for an incremental build) and pages.yml (the catalog
# to deploy next to a new web app). A script rather than a composite action so it can be
# tested against a fake `gh` on PATH (tests/scripts/test_fetch_latest_catalog.py).
#
# Usage: scripts/fetch_latest_catalog.sh DEST [--allow-none]
#
#   --allow-none  no "catalog-*" release yet is not an error (the very first build); DEST is
#                 left empty and the outputs say found=false. Without the flag it is an error.
#
# A release that exists but can't be downloaded or doesn't hold a catalog is always an error:
# a silent "no previous" would make the build re-fetch everything and could shrink the site.
#
# Needs GH_TOKEN (and GH_REPO outside a checkout). Writes found= and tag= to $GITHUB_OUTPUT
# when it is set.
set -euo pipefail

usage() {
  echo "usage: $0 DEST [--allow-none]" >&2
  exit 2
}

[ $# -ge 1 ] || usage
dest=$1
shift
allow_none=false
while [ $# -gt 0 ]; do
  case $1 in
    --allow-none) allow_none=true ;;
    *) usage ;;
  esac
  shift
done

emit() {
  if [ -n "${GITHUB_OUTPUT:-}" ]; then
    echo "$1" >>"$GITHUB_OUTPUT"
  fi
}

# One "<createdAt> <tag>" line per catalog release; ISO timestamps sort as text. Drafts are
# excluded: they are unpublished. A failing `gh` fails the script (set -e).
listing=$(gh release list --json tagName,createdAt --limit 1000 --exclude-drafts \
  --jq '.[] | select(.tagName | startswith("catalog-")) | "\(.createdAt) \(.tagName)"')

tag=""
if [ -n "$listing" ]; then
  tag=$(printf '%s\n' "$listing" | sort | tail -n 1 | cut -d' ' -f2)
fi

if [ -z "$tag" ]; then
  if [ "$allow_none" = true ]; then
    echo "No catalog-* release exists yet; there is no previous catalog."
    emit "found=false"
    emit "tag="
    exit 0
  fi
  echo "error: no catalog-* release exists, so there is no catalog to publish." >&2
  echo "Run the Catalog workflow first." >&2
  exit 1
fi

echo "Newest catalog release: $tag"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
gh release download "$tag" --pattern catalog.tar.gz --dir "$tmp"

mkdir -p "$dest"
tar -xzf "$tmp/catalog.tar.gz" -C "$dest"
if [ ! -f "$dest/manifest.json" ]; then
  echo "error: release $tag's catalog.tar.gz has no manifest.json at its top level." >&2
  exit 1
fi

echo "Extracted $tag into $dest"
emit "found=true"
emit "tag=$tag"
