$(document).ready(function () {
    let selectedEmployeeId = null;

    // Utility function for handling AJAX requests
    function handleAjaxRequest(url, method, data, onSuccess, onError, beforeSendMessage = "Loading...") {
        $.ajax({
            url: url,
            method: method,
            data: data,
            beforeSend: function () {
                $("#staticBackdrop .modal-body").html(`<p>${beforeSendMessage}</p>`);
            },
            success: onSuccess,
            error: onError,
        });
    }

    // Handle display leave dates
    $(".view-leave-dates").on("click", function () {
        const employeeId = $(this).data("id");
        if (!employeeId) return;

        handleAjaxRequest(
            `/employee/leave/details/`,
            "GET",
            { employee_id: employeeId },
            function (response) {
                const selectedDates = response.selected_dates || [];
                const modalBody = $("#staticBackdrop .modal-body");

                if (selectedDates.length > 0) {
                    const datesList = selectedDates.map(date => `<li>${date}</li>`).join("");
                    modalBody.html(`<ul>${datesList}</ul>`);
                } else {
                    modalBody.html("<p>No leave dates found for this employee.</p>");
                }

                const modalElement = new bootstrap.Modal(document.getElementById("staticBackdrop"));
                modalElement.show();
            },
            function () {
                $("#staticBackdrop .modal-body").html("<p>An error occurred while fetching the leave dates.</p>");
            }
        );
    });

    // Common handler for showing approval/rejection confirmation modals
    function showConfirmationModal(employeeId, message, modalId) {
        selectedEmployeeId = employeeId;
        $(`#${modalId}Message`).text(message);
        $(`#${modalId}`).modal("show");
    }

    // Handle Approve Button Click
    $(".employeeLeaveApprove").on("click", function () {
        showConfirmationModal($(this).data("id"), "Are you sure you want to approve this leave?", "leaveApproveConfirmationModal");
    });

    // Handle Reject Button Click
    $(".employeeLeaveReject").on("click", function () {
        showConfirmationModal($(this).data("id"), "Are you sure you want to reject this leave?", "leaveRejectConfirmationModal");
    });

    // Confirm Action (Approve/Reject)
    function confirmLeaveAction(status, modalId, badgeClass) {
        if (!selectedEmployeeId) return;
    
        $.ajax({
            url: "/employee/leave/details/",
            method: "POST",
            data: {
                leave_id: selectedEmployeeId,
                status: status,
                csrfmiddlewaretoken: $("input[name='csrfmiddlewaretoken']").val(),
            },
            success: function (response) {
    
                if (response.new_status && response.leave_id) {
                    // Disable the buttons
                    $(`#employeeLeaveApprove-${response.leave_id}`).prop("disabled", true);
                    $(`#employeeLeaveReject-${response.leave_id}`).prop("disabled", true);
    
                    // Update the status badge in the table
                    const newStatusBadge = getBadgeHtml(response.new_status);
                    $(`#statusBadge-${response.leave_id}`).html(newStatusBadge);

                    $("#total-employees-count").text(response.total_employees);
                    $("#total-approved-leaves-count").text(response.total_approved_leaves);
                    $("#total-pending-leaves-count").text(response.total_pending_leaves);

                    // Hide the modal
                    $(`#${modalId}`).modal("hide");
                } else {
                    console.error("Invalid response format from server:", response);
                    alert("Unexpected response format. Please contact support.");
                }
            },
            error: function (xhr) {
                const errorMessage =
                    xhr.responseJSON?.error || `An error occurred while updating the leave status. Please try again.`;
                console.error("AJAX Error:", xhr);
                alert(errorMessage);
            }
        });
    }
    
    // Helper function to determine badge HTML
    function getBadgeHtml(status) {
        let badgeClass = "";
        if (status === "Pending") badgeClass = "bg-warning";
        else if (status === "Approved") badgeClass = "bg-success";
        else badgeClass = "bg-danger";
    
        return `<span class="badge ${badgeClass}">${status}</span>`;
    }

    // Confirm Approve Action
    $("#confirmLeaveApprove").on("click", function () {
        confirmLeaveAction("Approved", "leaveApproveConfirmationModal", "bg-success");
    });

    // Confirm Reject Action
    $("#confirmLeaveReject").on("click", function () {
        confirmLeaveAction("Rejected", "leaveRejectConfirmationModal", "bg-danger");
    });
});
