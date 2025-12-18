#!/usr/bin/env node
/**
 * Copyright (c) Microsoft Corporation.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const os = require('os');

// Auto-install chromium if missing (before redirecting stderr so user sees output)
const playwrightCache = path.join(os.homedir(), '.cache', 'ms-playwright');
const chromiumDirs = fs.existsSync(playwrightCache)
  ? fs.readdirSync(playwrightCache).filter(d => d.startsWith('chromium-'))
  : [];

if (chromiumDirs.length === 0) {
  console.error('Chromium not found, installing...');
  try {
    execSync('npx playwright install chromium', { stdio: 'inherit' });
  } catch (e) {
    console.error('Failed to install chromium:', e.message);
    process.exit(1);
  }
}

// Parse --log-dir and redirect stderr to log file
const logDirIndex = process.argv.indexOf('--log-dir');
if (logDirIndex !== -1 && process.argv[logDirIndex + 1]) {
  const logDir = process.argv[logDirIndex + 1];
  fs.mkdirSync(logDir, { recursive: true });
  const logFile = path.join(logDir, 'playwright-mcp.log');
  const logStream = fs.createWriteStream(logFile, { flags: 'a' });
  process.stderr.write = logStream.write.bind(logStream);
  process.argv.splice(logDirIndex, 2);
}

const { program } = require('playwright-core/lib/utilsBundle');
const { decorateCommand } = require('playwright/lib/mcp/program');

const packageJSON = require('./package.json');
const p = program.version('Version ' + packageJSON.version).name('Playwright MCP');
decorateCommand(p, packageJSON.version);
void program.parseAsync(process.argv);
