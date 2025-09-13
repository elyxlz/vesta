#!/usr/bin/env python3

import json
import sys
from datetime import datetime

# Read hook input
input_data = json.loads(sys.stdin.read())

# Add timestamp to user message
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
message = f"[{timestamp}] {input_data.get('text', '')}"

# Return modified message
print(json.dumps({"text": message}))
sys.exit(0)
