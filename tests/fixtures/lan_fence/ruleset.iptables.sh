set -e
iptables-legacy -w -t nat -N CP-POST 2>/dev/null || true
iptables-legacy -w -t nat -F CP-POST
iptables-legacy -w -t nat -C POSTROUTING -s 172.18.0.0/16 -j CP-POST 2>/dev/null || iptables-legacy -w -t nat -I POSTROUTING 1 -s 172.18.0.0/16 -j CP-POST
iptables-legacy -w -t nat -A CP-POST ! -o cp-isolated -m comment --comment masquerade-172.18.0.0/16 -j MASQUERADE
iptables-legacy -w -t mangle -N CP-FWD 2>/dev/null || true
iptables-legacy -w -t mangle -F CP-FWD
iptables-legacy -w -t mangle -C FORWARD -i cp-isolated -j CP-FWD 2>/dev/null || iptables-legacy -w -t mangle -I FORWARD 1 -i cp-isolated -j CP-FWD
iptables-legacy -w -t mangle -N CP-IN 2>/dev/null || true
iptables-legacy -w -t mangle -F CP-IN
iptables-legacy -w -t mangle -C INPUT -i cp-isolated -j CP-IN 2>/dev/null || iptables-legacy -w -t mangle -I INPUT 1 -i cp-isolated -j CP-IN
iptables-legacy -w -t mangle -A CP-FWD -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment forward-established -j RETURN
iptables-legacy -w -t mangle -A CP-FWD -d 10.0.0.0/8 -m comment --comment rfc1918-10 -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 172.16.0.0/12 -m comment --comment rfc1918-172 -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 192.168.0.0/16 -m comment --comment rfc1918-192 -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 100.64.0.0/10 -m comment --comment cgnat -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 169.254.0.0/16 -m comment --comment link-local -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 203.0.113.0/24 -m comment --comment connected-203.0.113.0/24 -j DROP
iptables-legacy -w -t mangle -A CP-FWD -d 198.51.100.7/32 -m comment --comment egress-198.51.100.7 -j DROP
iptables-legacy -w -t mangle -A CP-IN -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment input-established -j RETURN
iptables-legacy -w -t mangle -A CP-IN -m comment --comment host -j DROP
ip6tables-legacy -w -t mangle -N CP6-FWD 2>/dev/null || true
ip6tables-legacy -w -t mangle -F CP6-FWD
ip6tables-legacy -w -t mangle -C FORWARD -i cp-isolated -j CP6-FWD 2>/dev/null || ip6tables-legacy -w -t mangle -I FORWARD 1 -i cp-isolated -j CP6-FWD
ip6tables-legacy -w -t mangle -N CP6-IN 2>/dev/null || true
ip6tables-legacy -w -t mangle -F CP6-IN
ip6tables-legacy -w -t mangle -C INPUT -i cp-isolated -j CP6-IN 2>/dev/null || ip6tables-legacy -w -t mangle -I INPUT 1 -i cp-isolated -j CP6-IN
ip6tables-legacy -w -t mangle -A CP6-FWD -m comment --comment ipv6-forward -j DROP
ip6tables-legacy -w -t mangle -A CP6-IN -m comment --comment ipv6-host -j DROP
