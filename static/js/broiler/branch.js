$(document).ready(function () {
    // Function to Load Branch List
    function loadBranchList() {
        $.ajax({
            url: "{% url 'branch_list' %}", // Replace with your actual endpoint
            type: "GET",
            success: function (response) {
                console.log(response)
                const table = $("#branch-table");
                const tableBody = $("#branch-table-body");

                // Clear the current table body and destroy the DataTable if initialized
                if ($.fn.DataTable.isDataTable(table)) {
                    table.DataTable().clear().destroy();
                }
                tableBody.empty();

                // Populate the table dynamically
                response.forEach((branch) => {
                    const modalId = `editBranchModal-${branch.id}`;
                    const formId = `edit-branch-form-${branch.id}`;

                    const tableRow = `
                        <tr>
                            <td>${branch.state}</td>
                            <td>${branch.branch_name}</td>
                            <td>
                                <button class="btn btn-primary edit-button" 
                                    data-bs-toggle="modal" 
                                    data-bs-target="#${modalId}" 
                                    data-id="${branch.id}" 
                                    data-state="${branch.state}" 
                                    data-branch-name="${branch.branch_name}">
                                    Edit
                                </button>
                                <button class="btn btn-danger delete-branch" 
                                data-id="${branch.id}">
                                Delete
                            </button>
                            </td>
                        </tr>
                    `;

                    const modal = `
                        <div class="modal fade" id="${modalId}" tabindex="-1" aria-labelledby="${modalId}-Label" aria-hidden="true">
                            <div class="modal-dialog">
                                <div class="modal-content">
                                    <div class="modal-header">
                                        <h5 class="modal-title">Edit Branch</h5>
                                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                    </div>
                                    <form id="${formId}">
                                        <div class="modal-body">
                                            <input type="hidden" name="branch-id" value="${branch.id}">
                                            <div class="mb-3">
                                                <label class="form-label">State</label>
                                                <input type="text" class="form-control" name="state" value="${branch.state}" required>
                                            </div>
                                            <div class="mb-3">
                                                <label class="form-label">Branch Name</label>
                                                <input type="text" class="form-control" name="branch_name" value="${branch.branch_name}" required>
                                            </div>
                                        </div>
                                        <div class="modal-footer">
                                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                                            <button type="submit" class="btn btn-primary">Save Changes</button>
                                        </div>
                                    </form>
                                </div>
                            </div>
                        </div>
                    `;

                    tableBody.append(tableRow);
                    $("body").append(modal);

                    // Add event listener for the form inside modal
                    $(`#${formId}`).off("submit").on("submit", function (e) {
                        e.preventDefault();

                        const jsonData = {
                            branch_id: $(`#${formId} [name="branch-id"]`).val(),
                            state: $(`#${formId} [name="state"]`).val(),
                            branch_name: $(`#${formId} [name="branch_name"]`).val(),
                        };

                        $.ajax({
                            url: `/branch/${branch.id}/`, // Endpoint for updating branch details
                            type: "PUT",
                            headers: {
                                "X-CSRFToken": "{{ csrf_token }}",
                                "Content-Type": "application/json",
                            },
                            data: JSON.stringify(jsonData),
                            success: function () {
                                loadBranchList(); // Reload table after update
                                $(`#${modalId}`).modal("hide"); // Hide modal after submission
                            },
                            error: function (xhr, status, error) {
                                console.error(`Update error: ${error}`);
                            },
                        });
                    });
                });

                // Reinitialize DataTable
                table.DataTable();
            },
            error: function (xhr, status, error) {
                console.error(`Failed to load branches: ${error}`);
            },
        });
    }

    // Load branch list on page load
    loadBranchList();

    // Add new branch
    $("#branch-form").on("submit", function (event) {
        event.preventDefault();

        const state = $("#state").val();
        const branchName = $("#branch_name").val();
        csrfToken = "{{ csrf_token }}";

        $.ajax({
            url: "/create-branch/", // Replace with your backend endpoint for adding branches
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken,
            },
            data: {
                state: state,
                branch_name: branchName,
            },
            success: function () {
                $("#branchFormModal").modal("hide");
                $("#branch-form")[0].reset();
                loadBranchList();
                alert("Branch added successfully!");
            },
            error: function (xhr, status, error) {
                console.error("Failed to add branch:", error);
                alert("An error occurred while adding the branch.");
            },
        });
    });

    // Handle delete button click
    $(document).on("click", ".delete-branch", function () {
        const id = $(this).data("id");
        csrfToken = "{{ csrf_token }}";

        if (confirm("Are you sure you want to delete this branch?")) {
            $.ajax({
                url: `/branch/${id}/delete/`, // Construct delete URL
                method: "DELETE",
                headers: { "X-CSRFToken": csrfToken },
                success: function () {
                    loadBranchList();
                    alert("Branch deleted successfully!");
                },
                error: function () {
                    alert("An error occurred while deleting the branch.");
                },
            });
        }
    });
});

