#!/bin/bash
# Backup daemon — runs backup every hour
while true; do
    bash /root/vesta/scripts/backup.sh
    sleep 3600
done
