#!/usr/bin/env bash
# Node side, before setup_node.sh, only if qualify_node.py reports landlock_abi < 4 (e.g. the 5.15
# kernel of CC-Ubuntu22.04-CUDA): the repository-task sandbox needs Landlock ABI 4 (kernel >= 6.7).
# Installs the Ubuntu HWE kernel (6.8) and gcc-12 (the HWE kernel is built with gcc-12; the NVIDIA DKMS
# module fails to build with the default gcc-11), checks the NVIDIA module exists for the new kernel,
# then reboots. Re-run setup_node.sh afterwards (it restores counter permissions lost on reboot).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo -n apt-get update -qq
sudo -n apt-get install -y -qq gcc-12
sudo -n apt-get install -y -qq linux-generic-hwe-22.04 || sudo -n dpkg --configure -a
K="$(ls -1 /lib/modules | sort -V | tail -1)"
test -f "/lib/modules/$K/updates/dkms/nvidia.ko" || { echo "no NVIDIA module for $K; not rebooting"; dkms status; exit 1; }
echo "rebooting into $K"
sudo -n systemctl reboot
