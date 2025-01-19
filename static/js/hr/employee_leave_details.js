$(document).ready(function () {
    let selectedEmployeeId = null;
    
    // handle display leave dates
    $(".view-leave-dates").on("click", function () {
        const employeeId = $(this).data("id"); // Get the employee ID from the button

        if (employeeId) {
            $.ajax({
                url: `/employee/leave/details/`, // API endpoint
                method: "GET",
                data: { employee_id: employeeId }, // Pass employee ID
                beforeSend: function () {
                    // Show a loader or clear the modal content before the request
                    $("#staticBackdrop .modal-body").html("<p>Loading...</p>");
                },
                success: function (response) {
                    const selectedDates = response.selected_dates || [];
                    const modalBody = $("#staticBackdrop .modal-body");

                    if (selectedDates.length > 0) {
                        // Create a list of leave dates
                        const datesList = selectedDates
                            .map(date => `<li>${date}</li>`)
                            .join("");
                        modalBody.html(`<ul>${datesList}</ul>`);
                    } else {
                        modalBody.html("<p>No leave dates found for this employee.</p>");
                    }

                    // Open the modal after successfully fetching data
                    const modalElement = new bootstrap.Modal(document.getElementById("staticBackdrop"));
                    modalElement.show();
                },
                error: function () {
                    $("#staticBackdrop .modal-body").html("<p>An error occurred while fetching the leave dates.</p>");
                },
            });
        }
    });

    // Handle Approve Button Click
    $(".employeeLeaveApprove").on("click", function () {
        selectedEmployeeId = $(this).data("id");
        $("#confirmationApproveMessage").text("Are you sure you want to approve this leave?");
        $("#leaveApproveConfirmationModal").modal("show");
    });

    // Handle Reject Button Click
    $(".employeeLeaveReject").on("click", function () {
        selectedEmployeeId = $(this).data("id");
        $("#confirmationRejectMessage").text("Are you sure you want to reject this leave?");
        $("#leaveRejectConfirmationModal").modal("show");
    });

    // Confirm Approve Action
    $("#confirmLeaveApprove").on("click", function () {
        if (selectedEmployeeId) {
            $.ajax({
                url: "/employee/leave/details/",
                method: "POST",
                data: {
                    leave_id: selectedEmployeeId,
                    status: "Approved",
                    csrfmiddlewaretoken: $("input[name='csrfmiddlewaretoken']").val(), // CSRF token
                },
                success: function (response) {
                    $("#confirmationApproveMessage").text("Leave approved successfully!");
                    setTimeout(() => location.reload(), 3000); // Reload after 3 seconds
                },
                error: function (xhr) {
                    const errorMessage = xhr.responseJSON?.error || "An error occurred while approving the leave. Please try again.";
                    $("#confirmationApproveMessage").text(errorMessage);
                    setTimeout(() => location.reload(), 3000); // Reload after 3 seconds
                },
            });
        }
    });

    // Confirm Reject Action
    $("#confirmLeaveReject").on("click", function () {
        if (selectedEmployeeId) {
            $.ajax({
                url: "/employee/leave/details/",
                method: "POST",
                data: {
                    leave_id: selectedEmployeeId,
                    status: "Rejected",
                    csrfmiddlewaretoken: $("input[name='csrfmiddlewaretoken']").val(), // CSRF token
                },
                success: function (response) {
                    $("#confirmationRejectMessage").text("Leave rejected successfully!");
                    setTimeout(() => location.reload(), 3000); // Reload after 3 seconds
                },
                error: function (xhr) {
                    const errorMessage = xhr.responseJSON?.error || "An error occurred while rejecting the leave. Please try again.";
                    $("#confirmationRejectMessage").text(errorMessage);
                    setTimeout(() => location.reload(), 3000); // Reload after 3 seconds
                },
            });
        }
    });
});
