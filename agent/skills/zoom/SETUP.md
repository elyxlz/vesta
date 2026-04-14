# Zoom Setup

1. Go to https://marketplace.zoom.us/ and sign in
2. Click "Develop" > "Build App" > choose **Server-to-Server OAuth**
3. Fill in the app name and basic info
4. Note down the **Account ID**, **Client ID**, and **Client Secret**
5. Under "Scopes", add: `meeting:write:admin`, `meeting:read:admin`
6. Activate the app
7. Install: `uv tool install ~/vesta/agent/skills/zoom/cli`
8. Run: `zoom setup` and enter the 3 credentials when prompted
