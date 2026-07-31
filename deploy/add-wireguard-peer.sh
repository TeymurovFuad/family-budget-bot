#!/usr/bin/env bash
# add-wireguard-peer.sh — generate keys for one new device (phone, laptop),
# register it as a peer on the server, and show a QR code to scan with the
# WireGuard app. Run once per device, as root, on the same VM as
# setup-wireguard-server.sh.
#
# Nothing is hardcoded — the device name and server endpoint are asked for
# interactively if not already known. The client private key is never
# printed to the terminal and the on-disk copy is deleted by default once
# you confirm the device is set up (see the prompt at the end).
set -euo pipefail

WG_DIR="/etc/wireguard"

prompt() {
    # prompt <env_var_name> <question> <default>
    local var="$1" question="$2" default="$3" value
    if [ -n "${!var:-}" ]; then
        printf '%s\n' "${!var}"
        return
    fi
    read -r -p "${question} [${default}]: " value </dev/tty
    printf '%s\n' "${value:-$default}"
}

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (sudo $0)" >&2
    exit 1
fi

WG_IFACE=$(prompt WG_IFACE "WireGuard interface name" "wg0")
[[ "$WG_IFACE" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Interface name must be alphanumeric/_/- only" >&2; exit 1; }
WG_PORT=$(prompt WG_PORT "WireGuard listen port (UDP)" "51820")
WG_SERVER_IP=$(prompt WG_SERVER_IP "WireGuard server tunnel IP" "10.8.0.1")
WG_SUBNET_CIDR=$(prompt WG_SUBNET_CIDR "WireGuard subnet size (CIDR bits)" "24")
WG_CLIENT_DNS=$(prompt WG_CLIENT_DNS "DNS server for the client to use" "1.1.1.1")

CONF="$WG_DIR/$WG_IFACE.conf"
PEER_DIR="$WG_DIR/peers"

if [ ! -f "$CONF" ]; then
    echo "$CONF not found — run setup-wireguard-server.sh first." >&2
    exit 1
fi

DEVICE_NAME="${1:-}"
if [ -z "$DEVICE_NAME" ]; then
    DEVICE_NAME=$(prompt WG_DEVICE_NAME "Name for this device (e.g. phone, laptop)" "")
fi
if [ -z "$DEVICE_NAME" ]; then
    echo "A device name is required." >&2
    exit 1
fi
[[ "$DEVICE_NAME" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Device name must be alphanumeric/_/- only (no spaces, slashes, or newlines)" >&2; exit 1; }

CLIENT_CONF="$PEER_DIR/$DEVICE_NAME.conf"
if [ -f "$CLIENT_CONF" ]; then
    echo "$CLIENT_CONF already exists — a peer named '$DEVICE_NAME' was already added." >&2
    echo "Pick a different device name, or remove the existing peer manually first." >&2
    exit 1
fi

DETECTED_ENDPOINT=$(curl -s --max-time 5 https://ifconfig.me || echo "")
ENDPOINT_DEFAULT="${DETECTED_ENDPOINT:-<this-server-public-ip-or-hostname>}"
WG_SERVER_ENDPOINT=$(prompt WG_SERVER_ENDPOINT "This server's public IP/hostname (for the client to connect to)" "$ENDPOINT_DEFAULT")
if [ "$WG_SERVER_ENDPOINT" = "<this-server-public-ip-or-hostname>" ]; then
    echo "Could not auto-detect a public IP and none was provided — re-run and supply one." >&2
    exit 1
fi

umask 077
mkdir -p "$PEER_DIR"

# Next free host address in the WG subnet: server is always .1, peers start at .2.
NEXT_OCTET=$(( $(grep -oE "AllowedIPs = ${WG_SERVER_IP%.*}\.[0-9]+" "$CONF" 2>/dev/null | grep -oE '[0-9]+$' | sort -n | tail -1 || echo 1) + 1 ))
PEER_IP="${WG_SERVER_IP%.*}.${NEXT_OCTET}"

# The client private key is generated in memory, never echoed, and lives only
# in $CLIENT_CONF (0600) and the QR code rendered below. Both are deleted at
# the end unless you explicitly choose to keep the file.
CLIENT_PRIVATE_KEY=$(wg genkey)
CLIENT_PUBLIC_KEY=$(printf '%s' "$CLIENT_PRIVATE_KEY" | wg pubkey)
SERVER_PUBLIC_KEY=$(cat "$WG_DIR/server_public.key")

cat >> "$CONF" <<EOF

[Peer]
# ${DEVICE_NAME}
PublicKey = ${CLIENT_PUBLIC_KEY}
AllowedIPs = ${PEER_IP}/32
EOF

wg syncconf "$WG_IFACE" <(wg-quick strip "$WG_IFACE")

cat > "$CLIENT_CONF" <<EOF
[Interface]
PrivateKey = ${CLIENT_PRIVATE_KEY}
Address = ${PEER_IP}/${WG_SUBNET_CIDR}
DNS = ${WG_CLIENT_DNS}

[Peer]
PublicKey = ${SERVER_PUBLIC_KEY}
Endpoint = ${WG_SERVER_ENDPOINT}:${WG_PORT}
AllowedIPs = ${WG_SERVER_IP}/32
PersistentKeepalive = 25
EOF
chmod 600 "$CLIENT_CONF"
unset CLIENT_PRIVATE_KEY

echo
echo "Peer '$DEVICE_NAME' added — assigned ${PEER_IP}."
echo
echo "Scan this QR code with the WireGuard app on the device now:"
echo
qrencode -t ansiutf8 < "$CLIENT_CONF"
echo

KEEP=$(prompt WG_KEEP_CONF "Scanned it? Delete the on-disk config now (recommended)? (yes/no)" "yes")
if [ "$KEEP" = "yes" ]; then
    if command -v shred >/dev/null 2>&1; then
        shred -u "$CLIENT_CONF"
    else
        rm -f "$CLIENT_CONF"
    fi
    echo "Deleted $CLIENT_CONF — the device's private key no longer exists anywhere but the device itself."
else
    echo "Kept $CLIENT_CONF (mode 600) — remember it contains a private key. Delete it once you no longer need it:"
    echo "  sudo shred -u $CLIENT_CONF"
fi
