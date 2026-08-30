import { defineConfig } from "wxt";

// WXT generates the MV3 manifest from this config + the files in entrypoints/.
// JSX/TSX for the popup is compiled by the TS toolchain via tsconfig.json
// ("jsx": "react-jsx"), so we don't use @wxt-dev/module-react — its dev-mode
// React-refresh plugin is incompatible with Rolldown-based Vite builds.
// Permissions mirror the legacy extension: talk to the local backend on
// loopback, read the active tab, and inject the content script on demand.
export default defineConfig({
  manifest: {
    name: "AutoFill Agent",
    description:
      "Local-first agentic form filler — preview a plan, one-click fill, and learn missing fields (secrets always manual).",
    permissions: ["storage", "activeTab", "scripting"],
    host_permissions: ["http://127.0.0.1:8000/*"],
  },
});
