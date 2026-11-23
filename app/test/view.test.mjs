import { test } from "node:test";
import assert from "node:assert/strict";
import {
  resolveUrl, workApiUrl, worksApiUrl, filterWorks, genreTags,
  buildUnits, unitOf, countLabel, stepUnit, initialMode,
  MODE_SPREAD, MODE_SINGLE, MODE_SCROLL,
} from "../src/view.js";

test("resolveUrl joins reader-relative paths against the origin", () => {
  assert.equal(resolveUrl("https://mangaka.itonami.cloud", "/img/x-p01"), "https://mangaka.itonami.cloud/img/x-p01");
  assert.equal(resolveUrl("https://mangaka.itonami.cloud", "/api/work/a%20b"), "https://mangaka.itonami.cloud/api/work/a%20b");
  assert.equal(resolveUrl("https://mangaka.itonami.cloud", null), null);
});

test("api urls encode the rkey", () => {
  assert.equal(workApiUrl("https://mangaka.itonami.cloud", "gh-arc0-1"), "https://mangaka.itonami.cloud/api/work/gh-arc0-1");
  assert.equal(worksApiUrl("https://mangaka.itonami.cloud"), "https://mangaka.itonami.cloud/api/works");
});

test("filterWorks matches title/series/genre/author case-insensitively", () => {
  const works = [
    { rkey: "a", title: "山犬と硯", series: "第1話", genre: "和風伝奇", author: "x" },
    { rkey: "b", title: "Ghost Hacker", series: "arc0-1", genre: "cyber-thriller", author: "y" },
  ];
  assert.equal(filterWorks(works, "").length, 2);
  assert.equal(filterWorks(works, "GHOST")[0].rkey, "b");
  assert.equal(filterWorks(works, "和風")[0].rkey, "a");
  assert.equal(filterWorks(works, "nomatch").length, 0);
});

test("genreTags splits like the reader SSR", () => {
  assert.deepEqual(genreTags("日常×科学グルメ"), ["日常", "科学グルメ"]);
  assert.deepEqual(genreTags("A・B/C"), ["A", "B", "C"]);
  assert.deepEqual(genreTags(""), []);
});

test("buildUnits keeps cover alone in spread mode (RTL parity)", () => {
  const pages = [1, 2, 3, 4, 5].map((n) => ({ n }));
  assert.deepEqual(buildUnits(pages, MODE_SPREAD), [[0], [1, 2], [3, 4]]);
  assert.deepEqual(buildUnits(pages, MODE_SINGLE), [[0], [1], [2], [3], [4]]);
  assert.deepEqual(buildUnits(pages, MODE_SCROLL), [[0], [1], [2], [3], [4]]);
  assert.deepEqual(buildUnits([], MODE_SPREAD), []);
});

test("countLabel and stepUnit walk the units", () => {
  const pages = [1, 2, 3].map((n) => ({ n }));
  const units = buildUnits(pages, MODE_SPREAD);
  assert.equal(countLabel(pages, [0]), "1 / 3");
  assert.equal(countLabel(pages, [1, 2]), "3–2 / 3");
  assert.equal(countLabel([], []), "0 / 0");
  assert.equal(unitOf(units, 2), 1);
  assert.equal(stepUnit(units, 0, +1), 1);
  assert.equal(stepUnit(units, 1, -1), 0);
  assert.equal(stepUnit(units, 0, -1), 0);
});

test("initialMode defaults to single on phone widths", () => {
  assert.equal(initialMode(390), MODE_SINGLE);
  assert.equal(initialMode(1280), MODE_SPREAD);
});
