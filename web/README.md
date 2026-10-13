# Security Site Designer — web app (no server needed)

Created by Brad Hall. Copyright © 2026 Brad Hall. All rights reserved.

This folder is the complete app as a static website: `index.html`, an offline service worker (`sw.js`), the app manifest and icons. Put it on any web host and you get a real link that anyone can open — and **install as an app** on phones, tablets and computers (it then works offline on site). Projects save on each device; use Export → Project file to move one, or run the team server for shared projects, sign-in and customer approvals.

## Get a real link in about 2 minutes (pick one)
- **Netlify (easiest):** sign in free at app.netlify.com → *Add new site → Deploy manually* → drag this whole folder onto the page. You get `https://<name>.netlify.app` immediately; set your own domain under *Domain settings*.
- **GitHub Pages:** push the repo (it already contains this app in `web/` and `.github/workflows/pages.yml`), then repo *Settings → Pages → Source: GitHub Actions*. Your link: `https://<user>.github.io/<repo>/`. (Free GitHub accounts need a public repo for Pages — put just this folder in its own public repo if your main repo is private.)
- **Vercel / Cloudflare Pages:** create a project and upload this folder.
- **Your own server:** copy the folder to any web root (nginx, Apache, IIS). HTTPS is required for installing as an app.

## Install it as an app
Open the link in Chrome or Edge → *Install app* (top bar) or the browser menu → *Install*. On iPhone/iPad: Safari → Share → *Add to Home Screen*. Android: Chrome menu → *Add to Home screen*.

## Notes
Map tiles, address search and the PDF/Excel/3D libraries load from the internet the first time; after that the libraries are kept for offline use. Default satellite tiles are Esri World Imagery (keep the on-screen attribution; get your own key for heavy commercial use).
