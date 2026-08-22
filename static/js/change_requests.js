/* Change Request submission — shared by every module's form and list page.
 *
 * A user who lacks the edit/delete right on a transaction can still raise a
 * request for one — the same "propose, then someone who holds the right
 * approves" shape hatch_entry_form.html and friends already had, just no
 * longer copy-pasted once per template. Every module wires this the same
 * way: a form's Save calls submitChangeRequest when request_mode is on, and
 * a list row's Delete calls submitDeleteChangeRequest when page_perms.delete
 * is false.
 */
(function () {
  "use strict";

  function csrf() {
    return document.cookie.split("; ").find((v) => v.startsWith("csrftoken="))
      ?.split("=")[1] || "";
  }

  /** Propose new values for an existing record. `editId` is the record being
   *  changed; `payloadData` is the same field-value object the module's own
   *  save call would have sent. */
  window.submitChangeRequest = async function (module, editId, payloadData, listUrl) {
    const note = prompt("Reason for this change (optional):") || "";
    const res = await fetch("/change_request_api/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({
        module, object_id: editId, action: "edit", payload: payloadData, note,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return window.showToast("danger", err.error || "Unable to submit change request.");
    }
    window.showToast("success", "Change request submitted for approval.");
    location.href = listUrl;
  };

  /** Propose deleting an existing record. Stays on the page — the row is
   *  still there until a reviewer approves it — so the caller supplies
   *  `onDone` to refresh the list rather than this navigating away. */
  window.submitDeleteChangeRequest = async function (module, objectId, onDone) {
    const note = prompt("Reason for deletion request (optional):");
    if (note === null) return;
    const res = await fetch("/change_request_api/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({
        module, object_id: objectId, action: "delete", note: note || "",
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return window.showToast("danger", err.error || "Unable to submit deletion request.");
    }
    window.showToast("success", "Deletion request submitted for approval.");
    if (onDone) onDone();
  };
})();
