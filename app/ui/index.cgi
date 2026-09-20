#!/bin/bash
#
# 直链 — CGI 入口
# - /api/info.json      返回内网/公网 IP 与默认跳转端口
# - /api/services.json  扫描 TCP 监听端口（>= MIN_LIST_PORT）
# - 其余路径映射到 app/www 静态文件
#
set -euo pipefail

APPNAME="zhilian"
BASE_PATH="/var/apps/${APPNAME}/target/www"
TARGET_PORT="5566"
MIN_LIST_PORT="7000"
EXCLUDED_PORTS="15244 49152"

URI_NO_QUERY="${REQUEST_URI%%\?*}"

json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

get_lan_ip() {
    local ip=""
    if command -v ip >/dev/null 2>&1; then
        ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {print $7; exit}')"
    fi
    if [ -z "$ip" ]; then
        ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
    fi
    printf '%s' "${ip:-127.0.0.1}"
}

get_wan_ip() {
    local ip url
    for url in \
        "https://api.ipify.org" \
        "https://ifconfig.me/ip" \
        "https://icanhazip.com"
    do
        if command -v curl >/dev/null 2>&1; then
            ip="$(curl -fsS --max-time 4 "$url" 2>/dev/null | tr -d '[:space:]')"
        elif command -v wget >/dev/null 2>&1; then
            ip="$(wget -qO- --timeout=4 "$url" 2>/dev/null | tr -d '[:space:]')"
        fi
        if [ -n "$ip" ]; then
            printf '%s' "$ip"
            return 0
        fi
    done
    return 1
}

guess_scheme() {
    case "$1" in
        443|8443|9443) printf 'https' ;;
        *) printf 'http' ;;
    esac
}

extract_port() {
    local addr="${1#[}"
    addr="${addr%]}"
    printf '%s' "${addr##*:}"
}

is_loopback_bind() {
    case "$1" in
        127.0.0.1:*|localhost:*|[::1]:*) return 0 ;;
    esac
    return 1
}

is_excluded_port() {
    local port="$1" p
    for p in $EXCLUDED_PORTS; do
        [ "$port" = "$p" ] && return 0
    done
    return 1
}

normalize_local_addr() {
    local line="$1"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [[ "$line" =~ ^\[.*\]:[0-9]+$ ]] || [[ "$line" =~ ^[^[:space:]]+:[0-9]+$ ]]; then
        printf '%s' "$line"
    else
        awk '{print $4}' <<<"$line"
    fi
}

read_listeners() {
    local ss_cmd candidate
    for candidate in ss /usr/sbin/ss /sbin/ss /usr/bin/ss; do
        if command -v "$candidate" >/dev/null 2>&1; then
            "$candidate" -tlnp 2>/dev/null \
                || "$candidate" -tln 2>/dev/null \
                || true
            return 0
        fi
    done
    if command -v netstat >/dev/null 2>&1; then
        netstat -tlnp 2>/dev/null | awk 'NR > 2 { print $0 }' \
            || netstat -tln 2>/dev/null | awk 'NR > 2 { print $0 }' \
            || true
        return 0
    fi
    local file line local_addr ip_hex port_hex port
    for file in /proc/net/tcp /proc/net/tcp6; do
        [ -r "$file" ] || continue
        while read -r _ local_addr _ st _; do
            [[ "$st" == "0A" ]] || continue
            ip_hex="${local_addr%%:*}"
            port_hex="${local_addr##*:}"
            [[ "$port_hex" =~ ^[0-9A-Fa-f]+$ ]] || continue
            port=$((16#$port_hex))
            is_excluded_port "$port" && continue
            [ "$port" -ge "$MIN_LIST_PORT" ] && [ "$port" -le 65535 ] || continue
            case "$ip_hex" in
                0100007F|00000000000000000000000000000001) continue ;;
            esac
            printf '*:%s\n' "$port"
        done <"$file"
    done
}

collect_ports() {
    declare -gA PORT_SEEN=()
    local line local_addr port
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        local_addr="$(normalize_local_addr "$line")"
        [ -z "$local_addr" ] && continue
        is_loopback_bind "$local_addr" && continue
        port="$(extract_port "$local_addr")"
        [[ "$port" =~ ^[0-9]+$ ]] || continue
        is_excluded_port "$port" && continue
        [ "$port" -ge "$MIN_LIST_PORT" ] && [ "$port" -le 65535 ] || continue
        PORT_SEEN[$port]=1
    done < <(read_listeners)
}

build_services_json() {
    collect_ports
    local first=1 port scheme
    printf '['
    while IFS= read -r port; do
        [ -z "$port" ] && continue
        scheme="$(guess_scheme "$port")"
        [ "$first" -eq 1 ] || printf ','
        first=0
        printf '{"port":%s,"scheme":"%s"}' "$port" "$scheme"
    done < <(printf '%s\n' "${!PORT_SEEN[@]}" | sort -n)
    printf ']'
}

if echo "$URI_NO_QUERY" | grep -qE '/api/info\.json/?$'; then
    lan_ip="$(get_lan_ip)"
    wan_ip="$(get_wan_ip)" || wan_ip="$lan_ip"
    echo "Content-Type: application/json; charset=utf-8"
    echo "Cache-Control: no-store"
    echo ""
    printf '{"lan_ip":"%s","wan_ip":"%s","port":%s}\n' \
        "$(json_escape "$lan_ip")" \
        "$(json_escape "$wan_ip")" \
        "$TARGET_PORT"
    exit 0
fi

if echo "$URI_NO_QUERY" | grep -qE '/api/services\.json/?$'; then
    echo "Content-Type: application/json; charset=utf-8"
    echo "Cache-Control: no-store"
    echo ""
    build_services_json
    echo ""
    exit 0
fi

REL_PATH="/"
case "$URI_NO_QUERY" in
    *index.cgi*) REL_PATH="${URI_NO_QUERY#*index.cgi}" ;;
esac
[ -z "$REL_PATH" ] || [ "$REL_PATH" = "/" ] && REL_PATH="/index.html"

TARGET_FILE="${BASE_PATH}${REL_PATH}"

if echo "$TARGET_FILE" | grep -q '\.\.'; then
    echo "Status: 400 Bad Request"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "Bad Request"
    exit 0
fi

if [ ! -f "$TARGET_FILE" ]; then
    echo "Status: 404 Not Found"
    echo "Content-Type: text/plain; charset=utf-8"
    echo ""
    echo "404 Not Found"
    exit 0
fi

case "${TARGET_FILE##*.}" in
    html|htm) mime="text/html; charset=utf-8" ;;
    css) mime="text/css; charset=utf-8" ;;
    js) mime="application/javascript; charset=utf-8" ;;
    json) mime="application/json; charset=utf-8" ;;
    png) mime="image/png" ;;
    jpg|jpeg) mime="image/jpeg" ;;
    svg) mime="image/svg+xml" ;;
    *) mime="application/octet-stream" ;;
esac

echo "Content-Type: $mime"
echo ""
cat "$TARGET_FILE"
