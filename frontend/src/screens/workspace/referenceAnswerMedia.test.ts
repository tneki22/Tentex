import assert from "node:assert/strict";
import test from "node:test";

import { legacyBoundImages, type ReferenceAnswerMedia } from "./referenceAnswerMedia";

const image = (materialId: string, label: string): ReferenceAnswerMedia => ({
  kind: "image",
  source: "binding",
  materialId,
  label,
  url: `/assets/${label}`,
  alt: label,
});

test("legacy markers consume only the answer source material in source order", () => {
  const media = [image("other", "other-1"), image("source", "source-1"), image("source", "source-2")];

  assert.deepEqual(
    legacyBoundImages(media, "source").map((item) => item.label),
    ["source-1", "source-2"],
  );
  assert.deepEqual(
    legacyBoundImages(media, null).map((item) => item.label),
    ["other-1", "source-1", "source-2"],
  );
});
