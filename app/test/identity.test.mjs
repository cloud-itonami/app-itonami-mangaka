import { test } from "node:test";
import assert from "node:assert/strict";
import { readBlueprint, deriveIdentity } from "../scripts/identity.mjs";

const BLUEPRINT = `{:itonami.blueprint/id "mangaka"
 :itonami.blueprint/name "mangaka (漫画家) — AI manga publishing and reworking"
 :itonami.blueprint/isic-rev5 "5819"
 :itonami.blueprint/domain :publishing/ai-manga}`;

test("deriveIdentity returns the single non-series identity", () => {
  const identity = deriveIdentity("app-itonami-mangaka", readBlueprint(BLUEPRINT));
  assert.equal(identity.id, "network.itonami.mangaka");
  assert.equal(identity.source, "app-itonami-mangaka");
  assert.equal(identity.title, "mangaka (漫画家) — AI manga publishing and reworking");
  assert.equal(identity.productName, "mangaka (漫画家) — AI manga publishing and reworking");
  assert.equal(identity.catalog, "https://mangaka.itonami.cloud/api");
  assert.equal(identity.origin, "https://mangaka.itonami.cloud");
});

test("deriveIdentity fails closed on a series name or wrong blueprint id", () => {
  assert.throws(() => deriveIdentity("app-itonami-cloud-itonami-isco-2641", readBlueprint(BLUEPRINT)));
  assert.throws(() => deriveIdentity("app-itonami-mangaka", readBlueprint(`{:itonami.blueprint/id "wrong" :itonami.blueprint/name "x"}`)));
});

test("productName strips forbidden filename characters", () => {
  const identity = deriveIdentity("app-itonami-mangaka", readBlueprint(`{:itonami.blueprint/id "mangaka" :itonami.blueprint/name "a/b:c*d"}`));
  assert.equal(identity.productName, "a b c d");
});
