import assert from "node:assert/strict";
import test from "node:test";

import type { SearchResultRead } from "../../api/search";
import { groupPlacesByMaterial, toSourcePlaces } from "./sourcePlaces";

const page = (
  pageNumber: number,
  fragmentIds: string[],
  text: string,
  alreadyBound = false,
) => ({
  page_number: pageNumber,
  fragment_ids: fragmentIds,
  quality: "native" as const,
  text,
  highlights: [{ start: 0, end: 4 }],
  already_bound: alreadyBound,
});

const result = (
  materialId: string,
  materialName: string,
  pages: ReturnType<typeof page>[],
): SearchResultRead => ({
  fragment_ids: pages.flatMap((item) => item.fragment_ids),
  material_id: materialId,
  material_name: materialName,
  presentation_kind: "pdf",
  block_id: `${materialId}-block-${pages[0].page_number}`,
  block_title: null,
  page_from: pages[0].page_number,
  page_to: pages[pages.length - 1].page_number,
  quality: "native",
  text: pages[0].text,
  highlights: [],
  matched_forms: [],
  already_bound: pages.some((item) => item.already_bound),
  pages,
});

test("block spanning pages becomes one place per page with its own preview", () => {
  const places = toSourcePlaces([
    result("m1", "Лекции.pdf", [
      page(71, ["f1"], "Второе неравенство"),
      page(72, ["f2", "f3"], "Доказательство"),
    ]),
  ]);

  assert.deepEqual(places.map((place) => place.pageNumber), [71, 72]);
  assert.deepEqual(places[1].fragmentIds, ["f2", "f3"]);
  assert.equal(places[1].text, "Доказательство");
  assert.equal(places[0].key, "m1:71");
});

test("same page found through two blocks merges into one place", () => {
  const places = toSourcePlaces([
    result("m1", "Лекции.pdf", [page(54, ["f1"], "Теорема 13.2")]),
    result("m1", "Лекции.pdf", [page(54, ["f1", "f2"], "Следствие", true)]),
  ]);

  assert.equal(places.length, 1);
  assert.deepEqual(places[0].fragmentIds, ["f1", "f2"]);
  assert.equal(places[0].alreadyBound, true);
  // Превью остаётся от лучшего по рангу попадания, а не от последнего слитого.
  assert.equal(places[0].text, "Теорема 13.2");
});

test("places keep server ranking order, grouping only sorts pages inside a file", () => {
  const places = toSourcePlaces([
    result("m2", "Семинары.pdf", [page(54, ["f9"], "Семинар")]),
    result("m1", "Лекции.pdf", [page(75, ["f1"], "Позже")]),
    result("m1", "Лекции.pdf", [page(71, ["f2"], "Раньше")]),
  ]);

  assert.deepEqual(places.map((place) => place.key), ["m2:54", "m1:75", "m1:71"]);

  const groups = groupPlacesByMaterial(places);
  assert.deepEqual(groups.map((group) => group.materialId), ["m2", "m1"]);
  assert.deepEqual(groups[1].places.map((place) => place.pageNumber), [71, 75]);
});
