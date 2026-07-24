# Vendored: snapshot_accname.js

`snapshot_accname.js` is a self-contained IIFE bundle that reconstructs the
accessibility snapshot in-page (WebDriver BiDi has no native AX-tree export). It
bundles:

- **[dom-accessibility-api](https://github.com/eps1lon/dom-accessibility-api)**
  v0.7.0, MIT licensed: the W3C accessible-name/role algorithm
  (`computeAccessibleName`, `getRole`, `isInaccessible`, `isDisabled`).
- Vesta's own `walker.js`, which walks the DOM using that library, assigns the
  numbered refs (`e1`, `e2`, ...), and keeps the ref -> element map in the page
  realm for coordinate resolution at action time.

## Rebuilding

The bundle is produced with esbuild from `walker.js`:

```bash
npm i dom-accessibility-api@0.7.0
npx esbuild walker.js --bundle --format=iife --minify --target=firefox115 --outfile=snapshot_accname.js
```

`walker.js` is kept in the PR history / upstream as the source; only the built
`snapshot_accname.js` ships in the skill (no build step at runtime).

---

## dom-accessibility-api (MIT License)

Copyright (c) 2020 Sebastian Silbermann

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
