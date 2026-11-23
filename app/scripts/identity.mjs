// Mangaka app identity (non-series).
//
// Mangaka is not a classification-series repository: blueprint.edn carries
// an ISIC key for the registry catalog (JUN-1439), not a series source.
// Per tauri-series-app-scaffold step 2 (non-series branch), identity is
// derived once from the repository name plus the canonical site, and
// package.json `itonami` is the single definition that tauri.conf.json,
// the Android applicationId and the store catalog id are generated from.
// No series name-parse branch is used here.
import { readAll } from "./edn.mjs";

export const REPO_NAME = "app-itonami-mangaka";
export const APP_ID = "network.itonami.mangaka";
export const BLUEPRINT_ID = "mangaka";
export const CATALOG = "https://mangaka.itonami.cloud/api";
export const ORIGIN = "https://mangaka.itonami.cloud";

/** The single blueprint map of a blueprint.edn text. */
export function readBlueprint(text) {
  const forms = readAll(text);
  const top = forms.length === 1 && Array.isArray(forms[0]) ? forms[0] : forms;
  const maps = top.filter((x) => x && typeof x === "object" && !Array.isArray(x) && "itonami.blueprint/id" in x);
  if (maps.length !== 1) throw new Error(`blueprint.edn must hold exactly one blueprint map, found ${maps.length}`);
  return maps[0];
}

/**
 * Identity for the mangaka (non-series) app. The repository name and the
 * blueprint id must agree; the title is the blueprint name verbatim.
 * `productName` is the Tauri-safe form with each of `\ / : * ? " < > |`
 * replaced by a space and whitespace runs collapsed, trimmed. Control
 * characters in the name, or an empty productName, fail closed.
 */
export function deriveIdentity(source, blueprint) {
  if (source !== REPO_NAME) {
    throw new Error(`not a mangaka repository name: ${JSON.stringify(source)} (expected ${JSON.stringify(REPO_NAME)})`);
  }
  const blueprintId = blueprint?.["itonami.blueprint/id"];
  if (blueprintId !== BLUEPRINT_ID) {
    throw new Error(`blueprint id ${JSON.stringify(blueprintId)} does not match repository ${JSON.stringify(REPO_NAME)} (expected ${JSON.stringify(BLUEPRINT_ID)})`);
  }
  const name = blueprint["itonami.blueprint/name"];
  if (typeof name !== "string" || !name.trim()) throw new Error("blueprint has no :itonami.blueprint/name");
  const title = name.trim();
  if (/[\u0000-\u001f]/.test(title)) throw new Error(`blueprint name is not usable as a product name: ${JSON.stringify(name)}`);
  const productName = title.replace(/[\\/:*?"<>|]/g, " ").replace(/\s+/g, " ").trim();
  if (!productName) throw new Error(`blueprint name is not usable as a product name: ${JSON.stringify(name)}`);
  return {
    source,
    slug: "mangaka",
    id: APP_ID,
    title,
    productName,
    catalog: CATALOG,
    origin: ORIGIN,
    stateSchema: "itonami.mangaka.v1",
  };
}
