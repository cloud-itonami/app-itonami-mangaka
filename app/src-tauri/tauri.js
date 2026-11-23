import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
require(path.join(process.cwd(), "..", "node_modules", "@tauri-apps", "cli", "tauri.js"));
