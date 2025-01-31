$(document).ready(function () {
    let selectedEmployeeId = null;
    let employeeTable = null; // Define the table instance outside

    function initializeDataTable() {
        if ($.fn.DataTable.isDataTable('#leaveTable')) {
            $('#leaveTable').DataTable().clear().destroy(); // Properly clear and destroy
            $('#leaveTable tbody').empty(); // Clear existing table rows
        }
    
        employeeTable = $('#leaveTable').DataTable({
            paging: true,
            searching: true,
            ordering: true,
            info: true,
            lengthChange: true,
            pageLength: 10,
            lengthMenu: [[10, 25, 50, -1], [10, 25, 50, "All"]],
            language: {
                emptyTable: "No leave records found",
                zeroRecords: "No matching records found"
            }
        });
    
        return employeeTable;
    }

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
    $(document).on("click", ".view-leave-dates", function () {
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
    $(document).on("click", ".employeeLeaveApprove", function () {
        showConfirmationModal($(this).data("id"), "Are you sure you want to approve this leave?", "leaveApproveConfirmationModal");
    });

    // Handle Reject Button Click
    $(document).on("click", ".employeeLeaveReject", function () {
        showConfirmationModal($(this).data("id"), "Are you sure you want to reject this leave?", "leaveRejectConfirmationModal");
    });

    // Confirm Action (Approve/Reject)
    function confirmLeaveAction(status, modalId) {
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

                    // Hide the modal
                    $(`#${modalId}`).modal("hide");

                    // Optionally, update other UI elements like counts
                    $("#total-employees-count").text(response.total_employees);
                    $("#total-approved-leaves-count").text(response.total_approved_leaves);
                    $("#total-pending-leaves-count").text(response.total_pending_leaves);
                } else {
                    console.error("Invalid response format from server:", response);
                    alert("Unexpected response format. Please contact support.");
                }
            },
            error: function (xhr) {
                const errorMessage = xhr.responseJSON?.error || "An error occurred while updating the leave status. Please try again.";
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
        confirmLeaveAction("Approved", "leaveApproveConfirmationModal");
    });

    // Confirm Reject Action
    $("#confirmLeaveReject").on("click", function () {
        confirmLeaveAction("Rejected", "leaveRejectConfirmationModal");
    });

    // Attach a change event listener to the input fields
    $("#fromDate, #toDate").change(function () {
        const fromDate = $("#fromDate").val();
        const toDate = $("#toDate").val();

        if (fromDate && toDate) {
            const payload = {
                from_date: fromDate,
                to_date: toDate
            };

            $.ajax({
                url: "/employee/leave/details/",
                method: "GET",
                data: payload,
                success: function (response) {
                    $("#total-employees-count").text(response.total_employees);
                    $("#total-approved-leaves-count").text(response.total_approved_leaves);
                    $("#total-pending-leaves-count").text(response.total_pending_leaves);
                    loaddatatable(response.leave_details);
                },
                error: function (xhr, status, error) {
                    console.log("Error:", error);
                }
            });
        } else {
            console.log("Please select both dates.");
        }
    });

    // Load datatable function
    function loaddatatable(employeeDetails) {
        if ($.fn.DataTable.isDataTable('#leaveTable')) {
            $('#leaveTable').DataTable().clear().destroy();
        }
    
        const tbody = $('#leaveTable tbody');
        tbody.empty();
    
        employeeDetails.forEach(employee => {
            const row = `
                <tr>
                    <td>${employee.employee__employee_id}</td>
                    <td>${employee.employee__full_name}</td>
                    <td>${employee.reason}</td>
                    <td>${employee.leave_type}</td>
                    <td>${employee.total_days}</td>
                    <td id="statusBadge-${employee.id}">
                        <span class="badge ${employee.status === 'Pending' ? 'bg-warning' : (employee.status === 'Approved' ? 'bg-success' : 'bg-danger')}">
                            ${employee.status}
                        </span>
                    </td>
                    <td class="selectedButton">
                        <button id="employeeViewLeave-${employee.id}" type="button" class="btn btn-sm btn-primary view-leave-dates" data-bs-toggle="modal" data-id="${employee.id}">
                            View
                        </button>
                        ${employee.status === 'Approved' || employee.status === 'Rejected' ?
                            `<button id="employeeLeaveApprove-${employee.id}" class="btn btn-sm btn-success employeeLeaveApprove" data-id="${employee.id}" disabled>Approve</button>
                            <button id="employeeLeaveReject-${employee.id}" class="btn btn-sm btn-danger employeeLeaveReject" data-id="${employee.id}" disabled>Reject</button>` :
                            `<button id="employeeLeaveApprove-${employee.id}" class="btn btn-sm btn-success employeeLeaveApprove" data-id="${employee.id}">Approve</button>
                            <button id="employeeLeaveReject-${employee.id}" class="btn btn-sm btn-danger employeeLeaveReject" data-id="${employee.id}">Reject</button>`
                        }
                    </td>
                </tr>
            `;
            tbody.append(row);
        });
    
        employeeTable = initializeDataTable(); // Re-initialize DataTable
    }
    
});