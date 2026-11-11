#!/usr/bin/env bash
# The owner's own domain, proved with Pebble (Let's Encrypt's own test ACME server) and its DNS
# stand-in on the stack's edge network: real HTTP-01 on port 80, a real certificate on 443.
set -euxo pipefail
DOM=rouh-proof.example.test
GW=$(docker network inspect rouh_edge -f '{{(index .IPAM.Config 0).Gateway}}')
PUB=$(curl -fsS https://1.1.1.1/cdn-cgi/trace | sed -n 's/^ip=//p')
echo "$PUB $DOM" | sudo tee -a /etc/hosts
curl -fsSL -o pebble.minica.pem https://raw.githubusercontent.com/letsencrypt/pebble/main/test/certs/pebble.minica.pem
cat > pebble.json <<J
{"pebble": {"listenAddress": "0.0.0.0:14000", "managementListenAddress": "0.0.0.0:15000",
  "certificate": "test/certs/localhost/cert.pem", "privateKey": "test/certs/localhost/key.pem",
  "httpPort": 80, "tlsPort": 443, "ocspResponderURL": "", "externalAccountBindingRequired": false}}
J
docker run -d --name challtestsrv --network rouh_edge --network-alias challtestsrv \
  ghcr.io/letsencrypt/pebble-challtestsrv:latest -defaultIPv6 "" -defaultIPv4 "$GW"
docker run -d --name pebble --network rouh_edge --network-alias pebble -p 15000:15000 -e PEBBLE_VA_NOSLEEP=1 \
  -v "$PWD/pebble.json:/test/config/pebble-config.json:ro" ghcr.io/letsencrypt/pebble:latest \
  -config /test/config/pebble-config.json -dnsserver challtestsrv:8053
sleep 5
# Before an owner exists, rouh domain refuses (checked earlier in the run); with one, it goes on.
rouh domain "$DOM" --acme-ca https://pebble:14000/dir --acme-root pebble.minica.pem 2>&1 | tee domain.log || true
docker ps --format '{{.Names}} {{.Ports}}' | tee ports.txt
curl -fsSk https://127.0.0.1:15000/roots/0 -o pebble-root.pem
for i in $(seq 1 30); do
  curl -sS --resolve "$DOM:443:127.0.0.1" --cacert pebble-root.pem -o /dev/null -w '%{http_code}\n' "https://$DOM/healthz" | grep -q 200 && break
  sleep 5
done
{
  echo "healthz: $(curl -sS --resolve "$DOM:443:127.0.0.1" --cacert pebble-root.pem -o /dev/null -w '%{http_code}' "https://$DOM/healthz")"
  echo "setup through the edge: $(curl -sS --resolve "$DOM:443:127.0.0.1" --cacert pebble-root.pem -o /dev/null -w '%{http_code}' "https://$DOM/setup")"
  echo "setup api through the edge: $(curl -sS --resolve "$DOM:443:127.0.0.1" --cacert pebble-root.pem -o /dev/null -w '%{http_code}' "https://$DOM/setup/api/state")"
  echo "plain http: $(curl -sS --resolve "$DOM:80:127.0.0.1" -o /dev/null -w '%{http_code} %{redirect_url}' "http://$DOM/")"
  echo "certificate: $(echo | openssl s_client -connect 127.0.0.1:443 -servername $DOM 2>/dev/null | openssl x509 -noout -issuer -subject -ext subjectAltName | tr '\n' ' ')"
  echo "sign-in page: $(curl -sS --resolve "$DOM:443:127.0.0.1" --cacert pebble-root.pem "https://$DOM/login" | grep -o '<title>[^<]*' | head -1)"
} | tee edge-result.txt
rouh open 2>&1 | tee open-domain.txt
rouh status 2>&1 | tee status-domain.txt
rouh domain --off 2>&1 | tee domain-off.txt
ss -Hltn | tee listening-after-off.txt
docker rm -f pebble challtestsrv
