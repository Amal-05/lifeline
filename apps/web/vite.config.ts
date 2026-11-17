import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
export default defineConfig({ plugins: [react(), VitePWA({ registerType: "autoUpdate", devOptions: { enabled: true }, manifest: { name: "Lifeline", short_name: "Lifeline", start_url: "/", display: "standalone", background_color: "#f7faf9", theme_color: "#124e4a", icons: [] }, workbox: { globPatterns: ["**/*.{js,css,html,svg,json}"] } })] });
