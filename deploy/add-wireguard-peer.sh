#!/usr/bin/env bash
# add-wireguard-peer.sh — generate keys for one new device (phone, laptop),
# register it as a peer on the server, and print a ready-to-scan QR code plus
# the raw client config as a fallback. Run once per device, as root, on the
# same VM as setup-wireguard-server.sh.
set -euo pipefail

WG_DIR="/etc/wireguard"
WG_IFACE="${WG_IFACE:-wg0}"
WG_PORT="${WG_PORT:-51820}"
WG_SERVER_IP="${WG_SERVER_IP:-10.8.0.1}"
WG_SUBNET_CIDR="${WG_SUBNET_CIDR:-24}"
WG_CLIENT_DNS="${WG_CLIENT_DNS:-1.1.1.1}"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this as root (sudo $0 <device-name>)" >&2
    exit 1
fi

DEVICE_NAME="${1:-}"
if [ -z "$DEVICE_NAME" ]; then
    echo "Usage: sudo $0 <device-name>   (e.g. sudo $0 phone)" >&2
    exit 1
fi

CONF="$WG_DIR/$WG_IFACE.conf"
PEER_DIR="$WG_DIR/peers"
CLIENT_CONF="$PEER_DIR/$DEVICE_NAME.conf"

if [ ! -f "$CONF" ]; then
    echo "$CONF not found — run setup-wireguard-server.sh first." >&2
    exit 1
fi

if [ -f "$CLIENT_CONF" ]; then
    echo "$CLIENT_CONF already exists — a peer named '$DEVICE_NAME' was already added." >&2
    echo "Pick a different device name, or remove the existing peer manually first." >&2
    exit 1
fi

mkdir -p "$PEER_DIR"
umask 077

# Next free host address in the WG subnet: server is always .1, peers start at .2.
NEXT_OCTET=$(( $(grep -oE 'AllowedIPs = 10\.8\.0\.[0-9]+' "$CONF" 2>/dev/null | grep -oE '[0-9]+$' | sort -n | tail -1 || echo 1) + 1 ))
PEER_IP="${WG_SERVER_IP%.*}.${NEXT_OCTET}"

CLIENT_PRIVATE_KEY=$(wg genkey)
CLIENT_PUBLIC_KEY=$(echo "$CLIENT_PRIVATE_KEY" | wg pubkey)
SERVER_PUBLIC_KEY=$(cat "$WG_DIR/server_public.key")
SERVER_ENDPOINT_IP="${WG_SERVER_ENDPOINT:-$(curl -s --max-time 5 https://ifconfig.me || echo "<your-server-public-ip>")}"

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
Endpoint = ${SERVER_ENDPOINT_IP}:${WG_PORT}
AllowedIPs = ${WG_SERVER_IP}/32
PersistentKeepalive = 25
EOF
chmod 600 "$CLIENT_CONF"

echo
echo "Peer '$DEVICE_NAME' added — assigned ${PEER_IP}."
echo
echo "Scan this QR code with the WireGuard app on the device:"
echo
qrencode -t ansiutf8 < "$CLIENT_CONF"
echo
echo "(Raw config also saved at $CLIENT_CONF if you'd rather import it as a file"
echo "or type it in manually. Delete it after the device is set up — it contains"
echo "a private key.)"
