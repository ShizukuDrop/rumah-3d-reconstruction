#!/usr/bin/env bash
set -euo pipefail
TASK=__TASK__
RELEASE=__RELEASE__
PREVIOUS=__PREVIOUS__
PROMOTED=0
NEXT=/var/www/rumah/current.native-next-$$
ROLLBACK=/var/www/rumah/current.native-rollback-$$
exec 9>/var/lib/vz/rumah-deploy/native-release.lock
flock -n 9
on_exit() {
    result=$?
    trap - EXIT
    if [ "$result" -ne 0 ] && [ "$PROMOTED" -eq 1 ]; then
        if [ "$(pct exec 710 -- readlink -f /var/www/rumah/current)" = "$RELEASE" ]; then
            if pct exec 710 -- ln -s "$PREVIOUS" "$ROLLBACK" && pct exec 710 -- mv -Tf "$ROLLBACK" /var/www/rumah/current; then
                date -Is > "$TASK/rollback.done"
                printf 'Verification failed; previous release restored.\n' >&2
            else
                printf 'Rollback failed; restore the retained previous release manually.\n' >&2
            fi
        else
            printf 'Current release changed concurrently; refusing to overwrite it.\n' >&2
        fi
    fi
    exit "$result"
}
trap on_exit EXIT
test ! -f "$TASK/deployed.done"
test "$(pct exec 710 -- readlink -f /var/www/rumah/current)" = "$PREVIOUS"
printf '%s\n' '__ARCHIVE_SHA__  __REMOTE_ARCHIVE__' | sha256sum -c -
pct exec 710 -- test ! -e "$RELEASE"
pct exec 710 -- nginx -t
pct exec 710 -- systemctl is-active nginx cloudflared
pct exec 710 -- cp -al "$PREVIOUS" "$RELEASE"
# Retire Full only from the newly cloned release. Unlinking these hardlinks
# leaves the previous release and its rollback data untouched.
pct exec 710 -- bash -s -- "$RELEASE" <<'REMOVE_FULL'
set -euo pipefail
release=$1
find "$release/models" -maxdepth 1 \( -type f -o -type l \) \( -iname 'iphone-full-*.glb' -o -iname 'iphone-full-*.glb.gz' \) -exec rm -f -- {} +
test ! -e "$release/models/iphone-full-room-16f8963b.glb"
test ! -e "$release/models/iphone-full-room-16f8963b.glb.gz"
REMOVE_FULL
# Detach every replacement before tar opens it, including identical hashed photos.
# No inode in the retained release is ever truncated or rewritten.
__DETACH__
pct exec 710 -- tar --no-same-owner --no-same-permissions -xf - -C "$RELEASE" < '__REMOTE_ARCHIVE__'
pct exec 710 -- bash -c 'set -euo pipefail; cd __RELEASE__; sha256sum -c -' <<'HASHES'
__HASHES__
HASHES
for asset in __PHONE_INODES__; do
    test "$(pct exec 710 -- stat -c '%d:%i' "$PREVIOUS/$asset")" = "$(pct exec 710 -- stat -c '%d:%i' "$RELEASE/$asset")"
done
test "$(pct exec 710 -- readlink -f /var/www/rumah/current)" = "$PREVIOUS"
pct exec 710 -- ln -s "$RELEASE" "$NEXT"
pct exec 710 -- mv -Tf "$NEXT" /var/www/rumah/current
PROMOTED=1
# GET only small authored HTML/JSON. Models are verified on disk and via HEAD.
pct exec 710 -- bash -s <<'VERIFY'
set -euo pipefail
test "$(curl -fsS --max-time 8 -H 'Accept-Encoding: identity' http://127.0.0.1/ | sha256sum | cut -d' ' -f1)" = __INDEX_SHA__
test "$(curl -fsS --max-time 8 -H 'Accept-Encoding: identity' http://127.0.0.1/__MANIFEST__ | sha256sum | cut -d' ' -f1)" = __MANIFEST_SHA__
head_asset() {
    curl -fsSI --max-time 8 -H "Accept-Encoding: $2" "http://127.0.0.1/$1"
}
while read -r asset model_length; do
    headers=$(head_asset "$asset" identity)
    test "$(printf '%s' "$headers" | awk 'tolower($1)=="content-length:"{gsub("\r", "", $2); print $2}')" = "$model_length"
    if printf '%s' "$headers" | grep -Eiq '^content-type:.*text/html|^www-authenticate:'; then exit 1; fi
done <<'NATIVE_MODELS'
__NATIVE_HEADS__
NATIVE_MODELS
for retired in models/iphone-full-room-16f8963b.glb models/iphone-full-room-16f8963b.glb.gz; do
    test "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 -I "http://127.0.0.1/$retired")" = 404
done
landing=$(head_asset '' identity)
printf '%s' "$landing" | grep -Eiq '^cache-control:.*(no-cache|no-store|max-age=0)'
if printf '%s' "$landing" | grep -Eiq '^www-authenticate:|^cache-control:.*immutable'; then exit 1; fi
for script in __JS_HEADS__; do
    headers=$(head_asset "$script" identity)
    printf '%s' "$headers" | grep -Eiq '^content-type:.*(application|text)/javascript'
done
while read -r asset raw_length gzip_length; do
    headers=$(head_asset "$asset" identity)
    test "$(printf '%s' "$headers" | awk 'tolower($1)=="content-length:"{gsub("\r", "", $2); print $2}')" = "$raw_length"
    headers=$(head_asset "$asset" gzip)
    printf '%s' "$headers" | grep -Eiq '^content-encoding: *gzip'
    test "$(printf '%s' "$headers" | awk 'tolower($1)=="content-length:"{gsub("\r", "", $2); print $2}')" = "$gzip_length"
done <<'GZIP_MODELS'
__GZIP_HEADS__
GZIP_MODELS
VERIFY
pct exec 710 -- systemctl is-active nginx cloudflared
date -Is > "$TASK/deployed.done"
printf 'Reviewed Osmo and iPhone Lite release promoted. Rollback retained.\n'
