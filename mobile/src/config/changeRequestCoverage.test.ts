/**
 * Every approval route the web offers, the phone can actually reach.
 *
 * `CHANGE_REQUEST_MODULE` says which modules have a handler, and
 * `REQUEST_EDIT_MODULES` which of those accept a proposed correction as well
 * as a deletion. Neither is enough on its own: the register only shows
 * "Request Edit" when `canProposeEdit` agrees, and that also asks whether this
 * app has an edit form to open. A module the web offers modification on, that
 * the phone has no form for, silently shows Request Deletion alone — which
 * reads as "the only thing wrong with a record can be its existence".
 *
 * A Django test (user/tests/test_mobile_change_requests.py) already keeps the
 * map in step with the handlers registered on the server. This is the other
 * half of the same question, and the half only the app can answer.
 */
import { CHANGE_REQUEST_MODULE, REQUEST_EDIT_MODULES, editRequestModule } from "./changeRequestModules";
import { canProposeEdit, hasEditForm } from "@/navigation/openForm";

describe("change request coverage", () => {
  it("can open a form for every module the web accepts a correction on", () => {
    const unreachable = Object.keys(CHANGE_REQUEST_MODULE)
      .filter((key) => editRequestModule(key) !== undefined)
      .filter((key) => !hasEditForm(key));
    expect(unreachable).toEqual([]);
  });

  it("offers Request Edit wherever the web does", () => {
    const missing = Object.entries(CHANGE_REQUEST_MODULE)
      .filter(([, module]) => REQUEST_EDIT_MODULES.has(module))
      .filter(([key]) => !canProposeEdit(key))
      .map(([key]) => key);
    expect(missing).toEqual([]);
  });

  it("names a module for every resource it offers a deletion request on", () => {
    // The delete fallback is gated on the map alone, so an entry whose module
    // key is empty would queue a request the server cannot route.
    const nameless = Object.entries(CHANGE_REQUEST_MODULE)
      .filter(([, module]) => !module)
      .map(([key]) => key);
    expect(nameless).toEqual([]);
  });

  it("does not claim an edit route for a module the web has none for", () => {
    // The reverse mistake: proposing a correction the approval queue would
    // refuse. REQUEST_EDIT_MODULES must be a subset of the handlers.
    const known = new Set(Object.values(CHANGE_REQUEST_MODULE));
    const strays = [...REQUEST_EDIT_MODULES].filter((m) => !known.has(m));
    expect(strays).toEqual([]);
  });
});
