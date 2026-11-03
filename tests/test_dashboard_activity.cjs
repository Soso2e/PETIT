"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { summarize, duration, intensity, dateUTC, DAYS } = require("../frontend/dashboard-activity.js");

const fixture = () => {
  const end = Date.UTC(2026, 10, 4);
  const daily = Array.from({ length: DAYS }, (_, i) => ({
    date: new Date(end - (DAYS - 1 - i) * 86400000).toISOString().slice(0, 10),
    elapsed_seconds: 0,
  }));
  return { days: DAYS, date_from: daily[0].date, date_to: daily.at(-1).date, daily };
};

test("90-day Dashboard uses real daily totals, without counting inactive days", () => {
  const source = fixture();
  source.daily[59].elapsed_seconds = 600;
  source.daily[62].elapsed_seconds = 7200;
  source.daily[88].elapsed_seconds = 1800;
  source.daily[89].elapsed_seconds = 3600;
  const data = summarize(source);
  assert.equal(data.daily.length, 90);
  assert.equal(data.last7, 5400);
  assert.equal(data.last30, 12600);
  assert.equal(data.activeDays30, 3);
  assert.equal(data.daily[59].seconds, 600);
});

test("empty 90-day period is not fabricated activity", () => {
  const data = summarize(fixture());
  assert.equal(data.last7, 0);
  assert.equal(data.last30, 0);
  assert.equal(data.activeDays30, 0);
});

test("invalid, non-contiguous, and negative daily records are rejected", () => {
  const invalidRange = fixture(); invalidRange.daily[8].date = "2026-10-31";
  assert.throws(() => summarize(invalidRange), /日別/);
  const invalidTime = fixture(); invalidTime.daily[89].elapsed_seconds = -10;
  assert.throws(() => summarize(invalidTime), /日別/);
  const missing = fixture(); missing.daily.pop();
  assert.throws(() => summarize(missing), /90日間/);
  assert.equal(dateUTC("2026-02-30"), null);
});

test("intensity and duration correspond to grounded session durations", () => {
  assert.deepEqual([0, 20, 1800, 3600, 7200].map(intensity), [0, 1, 2, 3, 4]);
  assert.equal(duration(7200 + 1800), "2時間30分");
  assert.equal(duration(0), "0分");
});
