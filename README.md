# Security Site Designer

**Created by Brad Hall** · © 2026 Brad Hall. All rights reserved.

Design CCTV, access control, intrusion and fire systems in three easy steps — floor plan, devices, quote & send — with live coverage, auto-design, wire-up, branded proposals, drawings, change orders and a customer presentation. The **Build Ready** dashboard answers one question — *can this be installed today?* — showing scale per floor, coverage, privacy, power, network, recording, cable runs, access and fire, open warnings, exports and approval, each with a fix button. The 🧰 Toolbox adds a lens & pixel calculator (IEC 62676-4), QR device labels, a camera list for your VMS, UPS runtime, conduit fill, IP plan and cable labels — and you can dictate site-walk and install notes.

**Open the app:** https://bradleyhall8601-web.github.io/security-site-designer/

Install it as an app from that link (Chrome/Edge: *Install app*; iPhone/iPad: Share → *Add to Home Screen*). It works offline on site; projects are saved on each device.

**Real product data:** every brand-name camera, reader, lock, controller, power supply and recorder in the catalog is checked against the manufacturer's datasheet or product page, and the app links that source on each device. Generic items are labelled *Generic*. You type your own option prices and monthly rates; the optional built-in BOM marks its generic-item prices as *estimate* so you can replace them.

**Honest status:** the app never says a system is wired, clean or ready until the checks pass. Auto-design reports what it actually did (cameras placed, coverage measured) and what is still open (powered, networked, on a recorder). A floor whose plan scale was never set is flagged everywhere its distances are used. Building-type presets (medical, retail, school, warehouse, restaurant, worship, parking, residential, office) mark privacy rooms and the detail level each room needs; they are a starting point, not legal advice. Fire alarm layouts are a layout aid — a licensed designer must engineer and permit the final system.

## Repository

- `web/` — the app, published to GitHub Pages on every push (`.github/workflows/pages.yml`).
- `e2e/` — live-site browser QA: `prod-qa.mjs` runs the full user and admin workflow (project setup, plan import, calibration, design, wiring, quote, every export, persistence, admin, keyboard, accessibility, responsive widths) against the deployed site using disposable QA projects only.
- `.github/workflows/browser-qa.yml` — after every deploy, runs that workflow on Windows in current stable **Google Chrome** and **Microsoft Edge**, and publishes the results, screenshots and every exported file to the `qa-results` branch.
