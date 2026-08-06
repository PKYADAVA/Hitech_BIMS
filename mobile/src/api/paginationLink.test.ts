/**
 * Following a pagination link must not leave the origin the app talks to.
 *
 * DRF writes `next`/`previous` as absolute URLs built from whatever address
 * Django saw the request arrive on. Behind the web build's proxy that is the
 * backend's own address, not the origin serving the page — so following the
 * link verbatim went cross-origin, hit an API that sends no Access-Control-*
 * headers, and the browser killed it before the app saw a response.
 *
 * The symptom was specific and confusing: every list worked, except the ones
 * long enough to have a second page. Daily Entries was the only one, so it
 * looked like a broken screen rather than broken paging.
 */
import { toApiPath } from "@/config";

describe("toApiPath", () => {
  it("keeps the path and query of an absolute link and drops the host", () => {
    expect(
      toApiPath("http://192.168.1.4:8000/api/v1/broiler/daily-entries/?cursor=cD0xMDA%3D")
    ).toBe("/broiler/daily-entries/?cursor=cD0xMDA%3D");
  });

  it("strips the api prefix so the base URL is not doubled", () => {
    // baseURL already contributes "/api/v1"; leaving it on the path would ask
    // for /api/v1/api/v1/... and 404.
    expect(toApiPath("https://bims.example.com/api/v1/inventory/items/?page=2"))
      .toBe("/inventory/items/?page=2");
  });

  it("handles a link with no query string", () => {
    expect(toApiPath("http://localhost:8000/api/v1/broiler/farms/"))
      .toBe("/broiler/farms/");
  });

  it("leaves an already-relative path alone", () => {
    expect(toApiPath("/broiler/farms/?page=3")).toBe("/broiler/farms/?page=3");
  });

  it("preserves every query parameter, not just the cursor", () => {
    expect(
      toApiPath("http://host:8000/api/v1/hr/trips/?date=2026-08-06&page=2&search=x")
    ).toBe("/hr/trips/?date=2026-08-06&page=2&search=x");
  });

  it("returns the input unchanged when it cannot be parsed", () => {
    // Never throw while paging: a link the app cannot read is better sent as
    // it came than turned into an exception mid-scroll.
    expect(toApiPath("")).toBe("");
  });
});
