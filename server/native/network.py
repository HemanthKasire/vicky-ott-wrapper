#!/usr/bin/python3
"""Allow only the existing private Docker bridge to reach the host-side native API."""
import ipaddress
import json
import subprocess
import sys

network = json.loads(subprocess.check_output(["docker", "network", "inspect", "n8n_default"]))[0]
interface = network.get("Options", {}).get("com.docker.network.bridge.name") or "br-" + network["Id"][:12]
ipam = next(entry for entry in network["IPAM"]["Config"] if ":" not in entry["Subnet"])
subnet = str(ipaddress.ip_network(ipam["Subnet"]))
gateway = str(ipaddress.ip_address(ipam["Gateway"]))
rule = ["INPUT", "-i", interface, "-s", subnet, "-d", gateway + "/32", "-p", "tcp", "--dport", "8090",
        "-m", "comment", "--comment", "oci-native-private-api", "-j", "ACCEPT"]
exists = subprocess.run(["iptables", "-w", "5", "-C", *rule], capture_output=True).returncode == 0
mode = sys.argv[1] if len(sys.argv) > 1 else "up"
if mode == "up" and not exists:
    subprocess.run(["iptables", "-w", "5", "-I", "INPUT", "1", *rule[1:]], check=True)
elif mode == "down" and exists:
    subprocess.run(["iptables", "-w", "5", "-D", *rule], check=True)
elif mode not in {"up", "down"}:
    raise SystemExit("Unknown mode")
