#!/usr/bin/env bash
# Install the pinned age (https://github.com/FiloSottile/age) on a Linux x64 runner, checked against its sha256.
# The same pin lives in .claude/lib/ai_editor/ghrender.py AGE_PINS (ghrender.py demo checks they match).
set -euo pipefail
AGE_VERSION=v1.2.1
AGE_SHA256=7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50
f="age-${AGE_VERSION}-linux-amd64.tar.gz"
curl -fsSL -o "/tmp/$f" "https://github.com/FiloSottile/age/releases/download/${AGE_VERSION}/$f"
echo "${AGE_SHA256}  /tmp/$f" | sha256sum -c --quiet -
tar -xzf "/tmp/$f" -C /tmp
sudo install -m 0755 /tmp/age/age /usr/local/bin/age
rm -rf "/tmp/$f" /tmp/age
age --version
